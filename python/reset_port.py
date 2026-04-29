#!/usr/bin/env python3
"""
Restart ESP32 connection - closes and reopens the serial port
"""
import serial
import time

def reset_port(port="COM5"):
    """Reset the serial port connection."""
    print(f"Attempting to reset {port}...")
    
    # Try to close any existing connection
    try:
        ser = serial.Serial(port)
        ser.close()
        print(f"Closed existing connection on {port}")
        time.sleep(2)
    except:
        pass
    
    # Test new connection
    try:
        ser = serial.Serial(port=port, baudrate=115200, timeout=1)
        time.sleep(2)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        print(f"✓ Successfully reconnected to {port}")
        
        # Read a few lines to verify
        print("Reading sensor output...")
        for i in range(5):
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"  {line}")
            time.sleep(0.2)
        
        ser.close()
        print("\n✓ Port is now ready for mqtt_publisher.py")
        
    except Exception as e:
        print(f"✗ Failed: {e}")

if __name__ == "__main__":
    reset_port("COM5")
