import json
import os
import time

import paho.mqtt.client as mqtt

from simulator import get_sensor_payload
from edge_ai import detect_peak

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
GROUP_ID = os.environ.get("GROUP_ID", "group25")
PROJECT_ID = os.environ.get("PROJECT_ID", "peak")
# Publishing interval in seconds (must match the simulation step size in simulator.py)
PUBLISH_INTERVAL = int(os.environ.get("PUBLISH_INTERVAL", "5"))

DATA_TOPIC = f"sensors/{GROUP_ID}/{PROJECT_ID}/data"
ALERT_TOPIC = f"alerts/{GROUP_ID}/{PROJECT_ID}/status"


def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected with result code {rc}")


def main():
    client = mqtt.Client(client_id="group25-peak-publisher")
    client.on_connect = on_connect
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except Exception as exc:
        print(f"[MQTT] Failed to connect to {MQTT_HOST}:{MQTT_PORT} — {exc}")
        raise
    client.loop_start()

    start_time = time.time()
    step_index = 0

    print(f"Publishing to {DATA_TOPIC} and {ALERT_TOPIC} via {MQTT_HOST}:{MQTT_PORT}")
    try:
        while True:
            payload = get_sensor_payload(start_time, step_index)
            client.publish(DATA_TOPIC, json.dumps(payload))
            print(f"[DATA] {payload}")

            if detect_peak(payload["power_kw"]):
                alert_payload = {
                    "timestamp": payload["timestamp"],
                    "power_kw": payload["power_kw"],
                    "status": "PEAK_DETECTED",
                    "reason": "threshold_or_zscore",
                    "group": GROUP_ID,
                    "project": PROJECT_ID,
                }
                client.publish(ALERT_TOPIC, json.dumps(alert_payload))
                print(f"[ALERT] {alert_payload}")

            step_index += 1
            time.sleep(PUBLISH_INTERVAL)
    except KeyboardInterrupt:
        print("Stopping publisher...")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
