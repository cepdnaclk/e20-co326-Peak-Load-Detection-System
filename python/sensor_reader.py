"""
Read real sensor data from ESP32 via serial connection.
Converts ADC readings to power consumption and peak detection status.
"""
import serial
import json
import time
from typing import Optional, Dict

class SensorReader:
    def __init__(self, port: str = "COM5", baudrate: int = 115200, timeout: float = 1.0):
        """
        Initialize serial connection to ESP32.
        
        Args:
            port: Serial port (e.g., "COM5" on Windows, "/dev/ttyUSB0" on Linux)
            baudrate: Baud rate (should match platformio.ini monitor_speed)
            timeout: Serial read timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None
        self.connected = False
        
        # Buffer for multi-line parsing (power and status on separate lines)
        self.last_power_data = None
        self.last_status = None
        
    def connect(self) -> bool:
        """Establish serial connection to ESP32."""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            time.sleep(2)  # Wait for ESP32 to reset after connection
            # Clear any buffered data from boot messages
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
        """Read a line from the serial port. Skips non-[POWER] lines."""
        try:
            if self.serial_conn:
                # Try to read a line with timeout
                if self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    return line if line else None
            return None
        except Exception as e:
            print(f"[SENSOR] Serial read error: {e}")
            return None
    
    def parse_sensor_data(self, line: str) -> Optional[Dict]:
        """
        Parse sensor data from ESP32 output.
        Supports TWO formats:
        1. Debug format: "Power   : 0.702 W" and separate "Status  : NORMAL" lines
        2. Compact format: "[POWER] Power: X.XX W | State: NORMAL/WARNING/PEAK"
        """
        try:
            # Check for compact [POWER] format first
            if "[POWER]" in line:
                parts = line.split("|")
                if len(parts) >= 2:
                    power_part = parts[0].split(":")[-1].strip()
                    power_w = float(power_part.split()[0])
                    
                    state_part = parts[1].split(":")[-1].strip()
                    state = state_part.split()[0]
                    
                    return {
                        "power_w": power_w,
                        "power_kw": power_w / 1000.0,
                        "state": state,
                        "is_peak": state == "PEAK"
                    }
            
            # Check for debug format: "Power   : 0.702 W"
            elif "Power   :" in line:
                # Extract power value (e.g., "0.702 W" -> 0.702)
                power_part = line.split(":")[-1].strip()
                power_w = float(power_part.split()[0])
                
                # State will be set from a separate line, default to NORMAL for now
                return {
                    "power_w": power_w,
                    "power_kw": power_w / 1000.0,
                    "state": "NORMAL",  # Will be updated by status line
                    "is_peak": False
                }
            
            # Check for status line: "Status  : NORMAL"
            elif "Status  :" in line:
                status_part = line.split(":")[-1].strip()
                state = status_part
                # Return just the state, will be merged with power data
                return {
                    "state": state,
                    "is_peak": state == "PEAK"
                }
                
        except (IndexError, ValueError) as e:
            # Silently skip unparseable lines
            pass
        
        return None
    
    def get_sensor_payload(self) -> Optional[Dict]:
        """
        Get the latest sensor reading and return formatted payload.
        Handles both single-line [POWER] format and multi-line debug format.
        Returns None if no complete data set is available yet.
        """
        max_attempts = 100  # Read multiple lines to find complete data set
        attempts = 0
        
        while attempts < max_attempts:
            line = self.read_line()
            if not line:
                attempts += 1
                continue
            
            data = self.parse_sensor_data(line)
            if not data:
                attempts += 1
                continue
            
            # Check if this is a complete data set (has both power and state)
            if "power_w" in data:
                # This is a power line
                self.last_power_data = data
            
            if "state" in data and "power_w" not in data:
                # This is a status line without power - just update state
                if self.last_power_data:
                    self.last_power_data["state"] = data["state"]
                    self.last_power_data["is_peak"] = data["is_peak"]
                    # Return the complete data
                    payload = self.last_power_data.copy()
                    return {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "power_kw": round(payload["power_kw"], 2),
                        "power_w": round(payload["power_w"], 2),
                        "state": payload["state"],
                        "is_peak": payload["is_peak"],
                        "group": "group25",
                        "project": "peak-load",
                        "mode": "peak" if payload["is_peak"] else "normal",
                    }
            
            elif "power_w" in data and "state" in data:
                # Complete data in one line (compact format)
                return {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "power_kw": round(data["power_kw"], 2),
                    "power_w": round(data["power_w"], 2),
                    "state": data["state"],
                    "is_peak": data["is_peak"],
                    "group": "group25",
                    "project": "peak-load",
                    "mode": "peak" if data["is_peak"] else "normal",
                }
            
            attempts += 1
        
        return None
    
    def disconnect(self):
        """Close the serial connection."""
        if self.serial_conn:
            self.serial_conn.close()
            self.connected = False
            print("[SENSOR] Disconnected")


if __name__ == "__main__":
    # Test the sensor reader
    reader = SensorReader(port="COM5")  # Change port as needed
    if reader.connect():
        print("Reading sensor data for 30 seconds...")
        start = time.time()
        while time.time() - start < 30:
            payload = reader.get_sensor_payload()
            if payload:
                print(f"[DATA] {payload}")
            time.sleep(0.1)
        reader.disconnect()
