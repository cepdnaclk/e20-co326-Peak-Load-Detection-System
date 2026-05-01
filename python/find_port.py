#!/usr/bin/env python3
"""
Find available COM ports and test ESP32
"""

import serial.tools.list_ports
import os

print("\n=== Available COM Ports ===\n")

ports = serial.tools.list_ports.comports()
if not ports:
    print("No COM ports found!")
    exit(1)

for i, port in enumerate(ports, 1):
    print(f"[{i}] {port.device:10} - {port.description}")

# Check environment variable
env_port = os.environ.get("SERIAL_PORT", "COM5")
print(f"\nCurrent SERIAL_PORT: {env_port}")

# Try to find ESP32 port
esp32_ports = [p for p in ports if "USB" in p.description or "CH340" in p.description or "Silicon" in p.description]

if esp32_ports:
    print(f"\n✓ Likely ESP32 port: {esp32_ports[0].device}")
    print(f"   Set with: $env:SERIAL_PORT='{esp32_ports[0].device}'")
else:
    print(f"\n? Could not auto-detect ESP32. Try each port above:")
    for p in ports:
        print(f"   $env:SERIAL_PORT='{p.device}'; python debug_serial.py")
