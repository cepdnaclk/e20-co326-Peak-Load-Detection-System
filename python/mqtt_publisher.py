"""
mqtt_publisher.py — Peak Load Detection: Serial-to-MQTT Bridge
===============================================================

Main entry point for the Python Edge AI system.

Data flow:
  ESP32 (USB Serial) → [this script] → MQTT Broker → Node-RED Dashboard
                                      → InfluxDB    → Grafana Dashboard

This script:
  1. Reads sensor data from ESP32 via serial (COM5)
  2. Runs Edge AI ensemble detection (threshold + Z-score + Isolation Forest)
  3. Publishes processed data to MQTT for Node-RED real-time dashboard
  4. Publishes peak alerts to MQTT for dashboard notifications
  5. Writes all data to InfluxDB for Grafana historical dashboards
  6. Falls back to the simulator if ESP32 is not connected

Usage:
  python mqtt_publisher.py

Environment variables (optional overrides):
  MQTT_HOST          MQTT broker hostname (default: localhost)
  MQTT_PORT          MQTT broker port (default: 1883)
  SERIAL_PORT        ESP32 serial port (default: COM5)
  USE_REAL_SENSOR    "true" to use ESP32, "false" for simulator (default: true)
  INFLUXDB_URL       InfluxDB URL (default: http://localhost:8086)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# Load .env from project root (one level up from python/)
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_env_path, override=False)  # override=False: real env vars take precedence

from sensor_reader import SensorReader
from simulator import get_sensor_payload
from edge_ai import detect_peak, detect_peak_full
from influxdb_writer import InfluxDBWriter

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MQTT_HOST        = os.environ.get("MQTT_HOST",        "localhost")
MQTT_PORT        = int(os.environ.get("MQTT_PORT",    "1883"))
GROUP_ID         = os.environ.get("GROUP_ID",          "group25")
PROJECT_ID       = os.environ.get("PROJECT_ID",        "peak")
SERIAL_PORT      = os.environ.get("SERIAL_PORT",       "COM5")
USE_REAL_SENSOR  = os.environ.get("USE_REAL_SENSOR",   "true").lower() == "true"
PUBLISH_INTERVAL = float(os.environ.get("PUBLISH_INTERVAL", "1"))

# MQTT Topics
TOPIC_DATA  = f"sensors/{GROUP_ID}/{PROJECT_ID}/data"
TOPIC_ALERT = f"alerts/{GROUP_ID}/{PROJECT_ID}/status"

# Relay state tracking
_peak_active      = False
_last_alert_time  = 0.0
_peak_cleared_at  = 0.0   # timestamp when peak last cleared
ALERT_COOLDOWN    = 8     # seconds between repeated ALERT publications
RELAY_RESTORE_DELAY = float(os.environ.get("RELAY_RESTORE_DELAY_S", "8"))  # seconds after clear before relay restores


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def iso_now() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# MQTT Callbacks (paho-mqtt v2 API)
# ---------------------------------------------------------------------------
def on_connect(client, userdata, connect_flags, reason_code, properties):
    if reason_code == 0 or str(reason_code) == "Success":
        logger.info("[MQTT] Connected to %s:%d", MQTT_HOST, MQTT_PORT)
    else:
        logger.error("[MQTT] Connection failed - reason=%s", reason_code)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    logger.warning("[MQTT] Disconnected (reason=%s) - will auto-reconnect...", reason_code)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global _peak_active, _last_alert_time, _peak_cleared_at

    print("=" * 60)
    print("  Peak Load Detection System — Group 25")
    print("  Serial-to-MQTT Bridge + InfluxDB Writer")
    print("=" * 60)

    # ---- Initialize MQTT ----
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{GROUP_ID}-peak-publisher",
    )
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect

    # Connect to MQTT with retry
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            break
        except OSError as exc:
            logger.warning("[MQTT] Connect failed: %s — retrying in 3s...", exc)
            time.sleep(3)

    client.loop_start()

    # ---- Initialize InfluxDB ----
    influx = InfluxDBWriter()
    influx_ok = influx.connect()
    if influx_ok:
        logger.info("[InfluxDB] Historical data persistence enabled")
    else:
        logger.warning("[InfluxDB] Not available — running without historical storage")

    # ---- Initialize sensor reader ----
    sensor = None
    use_real = USE_REAL_SENSOR
    if use_real:
        sensor = SensorReader(port=SERIAL_PORT)
        if not sensor.connect():
            logger.warning("[SENSOR] ESP32 not found on %s — falling back to simulator", SERIAL_PORT)
            use_real = False

    def send_relay_command(on: bool):
        """Send relay command back to ESP32 over serial."""
        if sensor and sensor.connected:
            cmd = "RELAY_ON\n" if on else "RELAY_OFF\n"
            try:
                sensor.serial_conn.write(cmd.encode('utf-8'))
                logger.info("[SERIAL] Sent: %s", cmd.strip())
            except Exception as e:
                logger.warning("[SERIAL] Failed to send relay command: %s", e)

    mode_label = "ESP32 SERIAL" if use_real and sensor else "SIMULATOR"

    print(f"  Mode:           {mode_label}")
    print(f"  MQTT Broker:    {MQTT_HOST}:{MQTT_PORT}")
    print(f"  Data topic:     {TOPIC_DATA}")
    print(f"  Alert topic:    {TOPIC_ALERT}")
    print(f"  InfluxDB:       {'ENABLED' if influx_ok else 'DISABLED'}")
    if use_real:
        print(f"  Serial port:    {SERIAL_PORT}")
    print("=" * 60)
    print("  Waiting for sensor data...\n")

    start_time = time.time()
    step_index = 0

    try:
        while True:
            # ---- Get sensor reading ----
            if use_real and sensor:
                raw = sensor.get_sensor_payload()
                if raw is None:
                    time.sleep(0.01)
                    continue
                power_w   = float(raw.get("power_w", 0.0))
                current_a = float(raw.get("current_a", 0.0))
                voltage_v = float(raw.get("voltage_v", 5.0))
                relay_on  = bool(raw.get("relay_on", True))
                button_held = bool(raw.get("button_held", False))
                ramp_w    = float(raw.get("ramp_w", 0.0))
            else:
                # Simulator mode
                sim = get_sensor_payload(start_time, step_index)
                power_w   = float(sim.get("power_kw", 0.3)) * 1000 * 0.005  # Scale to ~W range
                current_a = power_w / 5.0
                voltage_v = 5.0
                relay_on  = True
                button_held = False
                ramp_w    = 0.0

            ts = iso_now()

            # ---- Run Edge AI detection ----
            is_peak, state, is_warning = detect_peak(power_w)

            # Determine status string
            if is_peak:
                status = "PEAK"
            elif is_warning:
                status = "WARNING"
            else:
                status = "NORMAL"

            # ---- Build and publish data payload ----
            data_payload = {
                "timestamp": ts,
                "power_w":   round(power_w, 3),
                "current_a": round(current_a, 4),
                "voltage_v": voltage_v,
                "status":    status,
                "relay_on":  relay_on,
                "group":     GROUP_ID,
                "project":   "peak-load",
            }

            client.publish(TOPIC_DATA, json.dumps(data_payload), qos=0)
            print(f"[DATA] {status:7s} | {power_w:.3f} W | relay={'ON' if relay_on else 'OFF'}")

            # ---- Write to InfluxDB ----
            if influx_ok:
                influx.write_sensor_data(
                    power_w=power_w,
                    current_a=current_a,
                    voltage_v=voltage_v,
                    status=status,
                    relay_on=relay_on,
                    button_held=button_held,
                    ramp_w=ramp_w,
                )

            # ---- Handle peak alert ----
            now = time.time()
            if is_peak and (now - _last_alert_time) > ALERT_COOLDOWN:
                if not _peak_active:
                    _peak_active = True
                    send_relay_command(False)  # Trip relay on ESP32

                alert_payload = {
                    "timestamp": ts,
                    "power_w":   round(power_w, 3),
                    "status":    "PEAK_DETECTED",
                    "reason":    state,
                    "group":     GROUP_ID,
                    "project":   PROJECT_ID,
                }

                client.publish(TOPIC_ALERT, json.dumps(alert_payload), qos=0)
                print(f"[ALERT] *** PEAK at {power_w:.3f} W — {state} ***")
                _last_alert_time = now

                # Write alert to InfluxDB
                if influx_ok:
                    influx.write_peak_alert(power_w=power_w, reason=state)

            elif not is_peak and _peak_active:
                # Peak has cleared — start the restore cooldown timer
                if _peak_cleared_at == 0.0:
                    _peak_cleared_at = now
                    print(f"[AI]   Peak cleared — waiting {RELAY_RESTORE_DELAY:.0f}s before restoring relay...")

            # Restore relay only after cooldown has elapsed
            if _peak_active and _peak_cleared_at > 0.0 and (now - _peak_cleared_at) >= RELAY_RESTORE_DELAY:
                _peak_active = False
                _peak_cleared_at = 0.0
                send_relay_command(True)  # Restore relay on ESP32
                print(f"[AI]   Relay restored — cooldown complete")

            step_index += 1
            time.sleep(PUBLISH_INTERVAL)

    except KeyboardInterrupt:
        print("\n[BRIDGE] Shutting down...")
    finally:
        client.loop_stop()
        if sensor:
            sensor.disconnect()
        influx.close()
        client.disconnect()
        print("[BRIDGE] Clean shutdown complete.")


if __name__ == "__main__":
    main()
