#!/usr/bin/env python3
"""
Standalone runner for ESP32 Peak Load Detection
No Docker required. Reads from ESP32 serial, publishes to MQTT.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from sensor_reader import SensorReader
from edge_ai import detect_peak

# ===== Configuration =====
MQTT_HOST = os.environ.get("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
SERIAL_PORT = os.environ.get("SERIAL_PORT", "COM5")
GROUP_ID = os.environ.get("GROUP_ID", "group25")
PROJECT_ID = os.environ.get("PROJECT_ID", "peak")

# MQTT Topics
TOPIC_RAW = f"sensors/{GROUP_ID}/{PROJECT_ID}/raw"
TOPIC_PROCESSED = f"sensors/{GROUP_ID}/{PROJECT_ID}/data"

# ===== MQTT Client =====
def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected with result code {rc}")

def on_disconnect(client, userdata, rc):
    print(f"[MQTT] Disconnected with result code {rc}")

# ===== Main =====
def main():
    print("\n" + "="*60)
    print("  Peak Load Detection — Standalone (No Docker)")
    print("="*60)
    print(f"MQTT Broker: {MQTT_HOST}:{MQTT_PORT}")
    print(f"Serial Port: {SERIAL_PORT}")
    print(f"Topics: {TOPIC_RAW}, {TOPIC_PROCESSED}")
    print("="*60 + "\n")

    # Connect to MQTT
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="esp32-group25-standalone")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    try:
        print(f"[MQTT] Connecting to {MQTT_HOST}:{MQTT_PORT}...")
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[ERROR] MQTT connection failed: {e}")
        print("  Tip: Set MQTT_HOST to your broker IP or use 'broker.hivemq.com'")
        print("  Try: $env:MQTT_HOST='broker.hivemq.com'; python run_standalone.py")
        sys.exit(1)

    # Connect to ESP32 Serial
    print(f"[SENSOR] Connecting to {SERIAL_PORT}...")
    sensor = SensorReader(port=SERIAL_PORT, baudrate=115200, timeout=1.0)
    if not sensor.connect():
        print(f"[ERROR] Could not connect to {SERIAL_PORT}")
        print("  Available COM ports on Windows: COM1, COM3, COM4, COM5, etc.")
        print("  Check Device Manager (Ports) for your ESP32's COM port")
        sys.exit(1)

    print("\n[INFO] Reading from ESP32 and publishing to MQTT...")
    print("[INFO] Press Ctrl+C to stop\n")

    try:
        while True:
            # Read from serial
            line = sensor.read_line()
            if not line:
                time.sleep(0.1)
                continue

            # Parse sensor data
            data = sensor.parse_sensor_data(line)
            if not data:
                continue

            # Publish raw data
            timestamp = datetime.now(timezone.utc).isoformat() + "Z"
            payload = {
                "timestamp": timestamp,
                "power_w": data["power_w"],
                "power_kw": data["power_kw"],
                "state": data["state"],
                "group": GROUP_ID
            }

            client.publish(TOPIC_RAW, json.dumps(payload), qos=1)
            print(f"[PUB] {TOPIC_RAW}")
            print(f"      {payload}")

            # Run edge AI detection
            detection = detect_peak(data["power_w"])
            print(f"      Peak: {detection}")
            print()

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
    finally:
        client.loop_stop()
        client.disconnect()
        if sensor.connected:
            sensor.serial_conn.close()
        print("[INFO] Done!")

if __name__ == "__main__":
    main()
