#!/usr/bin/env python3
"""
Debug script to test ESP32 serial connection and data format.
Helps identify if sensor is working correctly.
"""

import serial
import sys
import time

def debug_serial(port="COM5", baudrate=115200, duration=10):
    """Read raw serial output and display it."""
    print(f"Connecting to {port} at {baudrate} baud...")
    
    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=1)
        time.sleep(2)  # Wait for ESP32 to reset
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(f"✓ Connected to {port}")
        print(f"Reading for {duration} seconds...\n")
        print("=" * 70)
        
        start = time.time()
        power_lines = 0
        other_lines = 0
        
        while time.time() - start < duration:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    if "[POWER]" in line:
                        print(f"✓ POWER: {line}")
                        power_lines += 1
                    else:
                        print(f"  OTHER:  {line}")
                        other_lines += 1
            time.sleep(0.01)
        
        print("=" * 70)
        print(f"\nSummary:")
        print(f"  Power lines ([POWER]): {power_lines}")
        print(f"  Other lines: {other_lines}")
        
        if power_lines == 0:
            print("\n⚠️  No [POWER] lines detected!")
            print("Possible causes:")
            print("  1. ESP32 is not outputting data (check main.cpp Serial.println calls)")
            print("  2. Wrong serial port (check Device Manager for actual port)")
            print("  3. Wrong baud rate (check platformio.ini monitor_speed)")
            print("  4. Serial cable not connected")
        else:
            print(f"\n✓ Sensor data is being transmitted correctly!")
        
        ser.close()
        
    except serial.SerialException as e:
        print(f"✗ Failed to open serial port: {e}")
        print("\nAvailable ports (Windows):")
        import subprocess
        try:
            subprocess.run(['powershell', '-c', 'Get-SerialPort'], check=False)
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    port = input("Enter serial port (default: COM5): ").strip() or "COM5"
    debug_serial(port=port, duration=15)
