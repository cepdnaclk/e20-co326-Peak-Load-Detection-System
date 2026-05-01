"""
sensor_reader.py — Read sensor data from ESP32 via USB serial
=============================================================

Parses JSON lines from the ESP32 serial output.

Expected ESP32 output format (one JSON line per reading):
  {"power_w":1.87,"current_a":0.374,"voltage_v":5.0,
   "relay_on":true,"button_held":false,"ramp_w":0.00,"status":"NORMAL"}

Also supports legacy formats:
  [SENSOR] Current: 0.260 A | Power: 1.30 W | Button: free | Ramp: 0.00 W | Relay: ON
"""

import json
import serial
import time
from typing import Optional, Dict


class SensorReader:
    def __init__(self, port: str = "COM5", baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None
        self.connected = False

    def connect(self) -> bool:
        """Establish serial connection to ESP32."""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            time.sleep(2)  # Wait for ESP32 to reset after connection
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            self.connected = True
            print(f"[SENSOR] Connected to {self.port} at {self.baudrate} baud")
            return True
        except Exception as e:
            print(f"[SENSOR] Failed to connect to {self.port}: {e}")
            self.connected = False
            return False

    def read_line(self) -> Optional[str]:
        """Read a line from the serial port."""
        try:
            if self.serial_conn and self.serial_conn.in_waiting > 0:
                line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                return line if line else None
            return None
        except Exception as e:
            print(f"[SENSOR] Serial read error: {e}")
            return None

    def parse_json_line(self, line: str) -> Optional[Dict]:
        """
        Parse a JSON line from ESP32.
        Expected: {"power_w":1.87,"current_a":0.374,"voltage_v":5.0,...}
        """
        try:
            data = json.loads(line)
            if "power_w" in data:
                return {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "power_w": float(data.get("power_w", 0.0)),
                    "power_kw": float(data.get("power_w", 0.0)) / 1000.0,
                    "current_a": float(data.get("current_a", 0.0)),
                    "voltage_v": float(data.get("voltage_v", 5.0)),
                    "relay_on": bool(data.get("relay_on", True)),
                    "button_held": bool(data.get("button_held", False)),
                    "ramp_w": float(data.get("ramp_w", 0.0)),
                    "status": data.get("status", "NORMAL"),
                    "group": "group25",
                    "project": "peak-load",
                }
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    def parse_legacy_line(self, line: str) -> Optional[Dict]:
        """
        Parse legacy [SENSOR] format from older ESP32 firmware.
        [SENSOR] Current: 0.260 A | Power: 1.30 W | Button: free | Ramp: 0.00 W | Relay: ON
        """
        try:
            if "[SENSOR]" not in line:
                return None

            parts = {}
            segments = line.split("|")
            for segment in segments:
                if ":" in segment:
                    key, val = segment.split(":", 1)
                    key = key.strip().lower().replace("[sensor]", "").strip()
                    val = val.strip()
                    parts[key] = val

            if "power" in parts:
                power_w = float(parts["power"].split()[0])
                relay_on = "on" in parts.get("relay", "on").lower()
                button_held = "held" in parts.get("button", "free").lower()
                ramp_w = float(parts.get("ramp", "0").split()[0]) if "ramp" in parts else 0.0
                current_a = float(parts.get("current", "0").split()[0]) if "current" in parts else power_w / 5.0

                return {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "power_w": power_w,
                    "power_kw": power_w / 1000.0,
                    "current_a": current_a,
                    "voltage_v": 5.0,
                    "relay_on": relay_on,
                    "button_held": button_held,
                    "ramp_w": ramp_w,
                    "status": "NORMAL",
                    "group": "group25",
                    "project": "peak-load",
                }
        except (IndexError, ValueError):
            pass
        return None

    def get_sensor_payload(self) -> Optional[Dict]:
        """
        Get the latest sensor reading. Tries JSON first, then legacy format.
        Returns None if no data available.
        """
        max_attempts = 50
        for _ in range(max_attempts):
            line = self.read_line()
            if not line:
                continue

            # Try JSON format first (new firmware)
            data = self.parse_json_line(line)
            if data:
                return data

            # Try legacy format
            data = self.parse_legacy_line(line)
            if data:
                return data

        return None

    def disconnect(self):
        """Close the serial connection."""
        if self.serial_conn:
            self.serial_conn.close()
            self.connected = False
            print("[SENSOR] Disconnected")


if __name__ == "__main__":
    reader = SensorReader(port="COM5")
    if reader.connect():
        print("Reading sensor data for 30 seconds...")
        start = time.time()
        while time.time() - start < 30:
            payload = reader.get_sensor_payload()
            if payload:
                print(f"[DATA] {json.dumps(payload)}")
            time.sleep(0.1)
        reader.disconnect()
