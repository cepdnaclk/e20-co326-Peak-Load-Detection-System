import json
import os
import time

import paho.mqtt.client as mqtt

from sensor_reader import SensorReader
from simulator import get_sensor_payload
from edge_ai import detect_peak

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
GROUP_ID = os.environ.get("GROUP_ID", "group25")
PROJECT_ID = os.environ.get("PROJECT_ID", "peak")
SERIAL_PORT = os.environ.get("SERIAL_PORT", "COM5")  # ESP32 serial port
USE_REAL_SENSOR = os.environ.get("USE_REAL_SENSOR", "false").lower() == "true"
PUBLISH_INTERVAL = int(os.environ.get("PUBLISH_INTERVAL", "1"))  # 1 second for real data

DATA_TOPIC = f"sensors/{GROUP_ID}/{PROJECT_ID}/data"
ALERT_TOPIC = f"alerts/{GROUP_ID}/{PROJECT_ID}/status"
STATUS_TOPIC = f"status/{GROUP_ID}/{PROJECT_ID}/live"


def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected with result code {rc}")


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="group25-peak-publisher")
    client.on_connect = on_connect
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except Exception as exc:
        print(f"[MQTT] Failed to connect to {MQTT_HOST}:{MQTT_PORT} — {exc}")
        raise
    client.loop_start()

    # Initialize sensor reader if using real data
    sensor = None
    use_real_sensor = USE_REAL_SENSOR
    if use_real_sensor:
        sensor = SensorReader(port=SERIAL_PORT)
        if not sensor.connect():
            print("[ERROR] Failed to connect to sensor. Falling back to simulator.")
            use_real_sensor = False
    
    start_time = time.time()
    step_index = 0
    last_alert_time = 0
    alert_cooldown = 5  # Seconds between alerts

    mode_label = "REAL SENSOR" if use_real_sensor and sensor else "SIMULATOR"
    print(f"Publishing ({mode_label}) to {DATA_TOPIC} via {MQTT_HOST}:{MQTT_PORT}")
    print("Waiting for sensor data...\n")
    try:
        while True:
            # Get payload from real sensor or simulator
            if use_real_sensor and sensor:
                payload = sensor.get_sensor_payload()
                if payload is None:
                    # Keep trying to read without blocking
                    time.sleep(0.01)
                    continue
            else:
                payload = get_sensor_payload(start_time, step_index)
            
            # Publish sensor data
            client.publish(DATA_TOPIC, json.dumps(payload))
            print(f"[DATA] {payload}")

            # Check for peak and send alert (with cooldown to avoid spam)
            is_peak = payload.get("is_peak", False) or detect_peak(payload["power_kw"])
            if is_peak and (time.time() - last_alert_time) > alert_cooldown:
                alert_payload = {
                    "timestamp": payload["timestamp"],
                    "power_kw": payload["power_kw"],
                    "power_w": payload.get("power_w", payload["power_kw"] * 1000),
                    "status": "PEAK_DETECTED",
                    "reason": payload.get("state", "threshold_or_zscore"),
                    "group": GROUP_ID,
                    "project": PROJECT_ID,
                }
                client.publish(ALERT_TOPIC, json.dumps(alert_payload))
                print(f"[ALERT] {alert_payload}")
                last_alert_time = time.time()

            step_index += 1
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        print("Stopping publisher...")
    finally:
        client.loop_stop()
        if sensor:
            sensor.disconnect()
        client.disconnect()


if __name__ == "__main__":
    main()
