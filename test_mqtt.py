#!/usr/bin/env python3
"""
Test script to publish sample data to MQTT for Node-RED testing
"""
import json
import time
import paho.mqtt.client as mqtt

# Configuration
MQTT_HOST = "localhost"
MQTT_PORT = 1883
DATA_TOPIC = "sensors/group25/peak/data"
ALERT_TOPIC = "alerts/group25/peak/status"

def publish_sample_data():
    """Publish sample power load data"""
    client = mqtt.Client(client_id="test-publisher")
    
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        print(f"✅ Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return
    
    client.loop_start()
    
    # Publish sample data
    payload = {
        "timestamp": "2026-04-28T10:00:00",
        "power_kw": 450,
        "group": "group25",
        "project": "peak",
        "mode": "normal"
    }
    
    client.publish(DATA_TOPIC, json.dumps(payload))
    print(f"📤 Published data: {payload}")
    time.sleep(1)
    
    # Publish sample alert
    alert_payload = {
        "timestamp": "2026-04-28T10:05:00",
        "power_kw": 850,
        "status": "PEAK_DETECTED",
        "reason": "threshold_or_zscore"
    }
    
    client.publish(ALERT_TOPIC, json.dumps(alert_payload))
    print(f"⚠️  Published alert: {alert_payload}")
    time.sleep(1)
    
    client.loop_stop()
    print("✅ Test complete!")

if __name__ == "__main__":
    publish_sample_data()
