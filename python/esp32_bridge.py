"""
esp32_bridge.py - Group 25 Peak Load Detection System
======================================================
Subscribes to the ESP32 raw MQTT topic, runs Edge AI peak detection,
and publishes processed results + alerts.

Topics:
  Subscribe:  sensors/group25/peak/raw
  Publish:    sensors/group25/peak/data
              alerts/group25/peak/status
              commands/group25/peak/relay
"""

import json
import os
import sys
import time
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from edge_ai import detect_peak

# ----------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ----------------------------------------------------------------
MQTT_HOST           = os.environ.get("MQTT_HOST",            "broker.hivemq.com")
MQTT_PORT           = int(os.environ.get("MQTT_PORT",        "1883"))
GROUP_ID            = os.environ.get("GROUP_ID",             "group25")
PROJECT_ID          = os.environ.get("PROJECT_ID",           "peak")
PEAK_THRESHOLD_W    = float(os.environ.get("PEAK_THRESHOLD_W",   "1.5"))
WARNING_RATIO       = float(os.environ.get("WARNING_RATIO",       "0.75"))
RELAY_RESTORE_DELAY = float(os.environ.get("RELAY_RESTORE_DELAY_S", "8"))

INFLUXDB_URL    = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN  = os.environ.get("INFLUXDB_TOKEN", "peak-token-group25")
INFLUXDB_ORG    = os.environ.get("INFLUXDB_ORG", "group25")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "peak_load")

_influx_client = None
_write_api = None

# Derived thresholds
WARNING_THRESHOLD_W = PEAK_THRESHOLD_W * WARNING_RATIO  # 1.125 W

# ---- MQTT Topics ----
TOPIC_RAW   = f"sensors/{GROUP_ID}/{PROJECT_ID}/raw"
TOPIC_DATA  = f"sensors/{GROUP_ID}/{PROJECT_ID}/data"
TOPIC_ALERT = f"alerts/{GROUP_ID}/{PROJECT_ID}/status"
TOPIC_RELAY = f"commands/{GROUP_ID}/{PROJECT_ID}/relay"

# ---- State ----
_peak_active         = False    # True while a peak is ongoing
_relay_on            = True     # Last known relay state
_relay_restore_timer = None     # threading.Timer for delayed relay restore


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def iso_now() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def publish(client: mqtt.Client, topic: str, payload: dict, label: str = "") -> None:
    """Serialize and publish a JSON payload."""
    msg = json.dumps(payload)
    client.publish(topic, msg, qos=0)
    tag = f"[{label}]" if label else "[PUB]"
    print(f"{tag} -> {topic}")
    print(f"       {msg}")


def schedule_relay_restore(client: mqtt.Client) -> None:
    """Cancel any pending restore and schedule a new one after RELAY_RESTORE_DELAY."""
    global _relay_restore_timer

    if _relay_restore_timer is not None:
        _relay_restore_timer.cancel()

    def _restore():
        global _relay_restore_timer
        _relay_restore_timer = None
        if not _peak_active:        # Only restore if still clear
            print("[RELAY] Restoring relay after cooldown...")
            client.publish(TOPIC_RELAY, "ON", qos=0)
            print(f"[RELAY] -> {TOPIC_RELAY}: ON")

    _relay_restore_timer = threading.Timer(RELAY_RESTORE_DELAY, _restore)
    _relay_restore_timer.daemon = True
    _relay_restore_timer.start()
    print(f"[RELAY] Restore scheduled in {RELAY_RESTORE_DELAY}s")


# ----------------------------------------------------------------
# MQTT Callbacks  (paho-mqtt 2.x VERSION2 signatures)
# ----------------------------------------------------------------
def on_connect(client: mqtt.Client, userdata, connect_flags, reason_code, properties) -> None:
    if reason_code == 0 or str(reason_code) == "Success":
        print(f"[MQTT] Connected to {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(TOPIC_RAW, qos=0)
        print(f"[MQTT] Subscribed to: {TOPIC_RAW}")
    else:
        print(f"[MQTT] Connection failed - reason={reason_code}")


def on_disconnect(client: mqtt.Client, userdata, disconnect_flags, reason_code, properties) -> None:
    print(f"[MQTT] Disconnected (reason={reason_code}) - will auto-reconnect...")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
    """Process a raw sensor reading from the ESP32."""
    global _peak_active, _relay_on

    # ---- Parse JSON ----
    try:
        raw = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"[WARN] Could not parse message: {exc}")
        return

    power_w   = float(raw.get("power_w",   0.0))
    current_a = float(raw.get("current_a", 0.0))
    voltage_v = float(raw.get("voltage_v", 5.0))
    relay_on  = bool( raw.get("relay_on",  True))
    ts        = iso_now()

    print(f"\n[RAW] power={power_w:.3f}W  current={current_a:.4f}A  relay={'ON' if relay_on else 'OFF'}")

    # ---- Peak detection via Edge AI ----
    is_peak, state, is_warning = detect_peak(power_w)

    # ---- Determine status string ----
    if is_peak:
        status = "PEAK"
    elif is_warning:
        status = "WARNING"
    else:
        status = "NORMAL"

    # ---- Build and publish processed data payload ----
    data_payload = {
        "timestamp": ts,
        "power_w":   round(power_w,   3),
        "current_a": round(current_a, 4),
        "voltage_v": voltage_v,
        "status":    status,
        "relay_on":  relay_on,
        "group":     GROUP_ID,
        "project":   "peak-load",
    }
    publish(client, TOPIC_DATA, data_payload, "DATA")

    # ---- Write to InfluxDB ----
    if _write_api:
        try:
            point = Point("peak_data") \
                .tag("group", GROUP_ID) \
                .tag("status", status) \
                .field("power_w", float(power_w)) \
                .field("current_a", float(current_a)) \
                .field("voltage_v", float(voltage_v)) \
                .field("relay_on", int(relay_on)) \
                .time(datetime.now(timezone.utc), WritePrecision.MS)
            _write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
        except Exception as e:
            print(f"[WARN] InfluxDB write failed: {e}")

    # ---- Handle PEAK logic ----
    if is_peak:
        if not _peak_active:
            _peak_active = True

            # Publish alert
            reason_str = state.lower().replace(" + ", "_and_").replace(" ", "_")
            alert_payload = {
                "timestamp": ts,
                "power_w":   round(power_w, 3),
                "status":    "PEAK_DETECTED",
                "reason":    reason_str,
                "group":     GROUP_ID,
            }
            publish(client, TOPIC_ALERT, alert_payload, "ALERT")

            # Write alert to InfluxDB
            if _write_api:
                try:
                    point = Point("peak_alert") \
                        .tag("group", GROUP_ID) \
                        .tag("status", "PEAK_DETECTED") \
                        .tag("reason", reason_str) \
                        .field("power_w", float(power_w)) \
                        .time(datetime.now(timezone.utc), WritePrecision.MS)
                    _write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
                except Exception as e:
                    print(f"[WARN] InfluxDB alert write failed: {e}")

            # Trip relay if it is currently on
            if relay_on:
                client.publish(TOPIC_RELAY, "OFF", qos=0)
                print(f"[RELAY] -> {TOPIC_RELAY}: OFF  (peak detected - tripping load)")

    else:
        # Peak has cleared
        if _peak_active:
            _peak_active = False
            print(f"[AI]   Peak cleared - status now {status}")
            schedule_relay_restore(client)


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main() -> None:
    print("=" * 56)
    print("  Peak Load Detection - ESP32 Bridge  (Group 25)")
    print("=" * 56)
    print(f"  Broker:            {MQTT_HOST}:{MQTT_PORT}")
    print(f"  Subscribe:         {TOPIC_RAW}")
    print(f"  Publish data:      {TOPIC_DATA}")
    print(f"  Publish alerts:    {TOPIC_ALERT}")
    print(f"  Relay commands:    {TOPIC_RELAY}")
    print(f"  Peak threshold:    {PEAK_THRESHOLD_W} W")
    print(f"  Warning threshold: {WARNING_THRESHOLD_W:.4f} W  ({int(WARNING_RATIO*100)}%)")
    print(f"  Relay restore:     {RELAY_RESTORE_DELAY}s after peak clears")
    print("=" * 56)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"python-esp32-bridge-{GROUP_ID}",
    )
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    # ---- Setup InfluxDB ----
    global _influx_client, _write_api
    try:
        _influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
        _write_api = _influx_client.write_api(write_options=SYNCHRONOUS)
        print(f"[INFLUXDB] Connected to {INFLUXDB_URL} (bucket={INFLUXDB_BUCKET})")
    except Exception as e:
        print(f"[WARN] InfluxDB init failed: {e}")

    # ---- Connect with retry ----
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            break
        except OSError as exc:
            print(f"[MQTT] Connect failed: {exc} - retrying in 5s...")
            time.sleep(5)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[BRIDGE] Shutting down...")
        if _relay_restore_timer:
            _relay_restore_timer.cancel()
        client.disconnect()
        sys.exit(0)


if __name__ == "__main__":
    main()
