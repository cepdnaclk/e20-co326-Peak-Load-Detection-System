#!/usr/bin/env python3
"""
Debug version - Shows raw serial data from ESP32
"""

import os
from sensor_reader import SensorReader

SERIAL_PORT = os.environ.get("SERIAL_PORT", "COM5")

print(f"[DEBUG] Reading raw data from {SERIAL_PORT}...")
print("(This will show exactly what ESP32 is sending)\n")

sensor = SensorReader(port=SERIAL_PORT, baudrate=115200, timeout=1.0)
if not sensor.connect():
    print(f"[ERROR] Could not open {SERIAL_PORT}")
    exit(1)

try:
    line_count = 0
    while True:
        line = sensor.read_line()
        if line:
            line_count += 1
            print(f"[{line_count}] {line}")
            
            # Try to parse it
            data = sensor.parse_sensor_data(line)
            if data:
                print(f"    ✓ Parsed: power={data['power_w']}W, state={data['state']}")
            else:
                print(f"    ✗ Could not parse this line")
            print()
except KeyboardInterrupt:
    print("\n[Done]")
finally:
    sensor.serial_conn.close()
