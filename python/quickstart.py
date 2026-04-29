#!/usr/bin/env python3
"""
Quick start script for Peak Load Detection System with real sensor data
Handles setup, MQTT broker check, and starts the publisher
"""

import subprocess
import sys
import os
import time
import platform

def run_command(cmd, shell=False):
    """Run a command and return success status"""
    try:
        if shell:
            subprocess.run(cmd, shell=True, check=True)
        else:
            subprocess.run(cmd.split(), check=True)
        return True
    except subprocess.CalledProcessError:
        return False
    except FileNotFoundError:
        return False

def install_dependencies():
    """Install required Python packages"""
    print("📦 Installing Python dependencies...")
    if run_command(f"{sys.executable} -m pip install -r requirements.txt"):
        print("✓ Dependencies installed")
        return True
    else:
        print("✗ Failed to install dependencies")
        return False

def check_mqtt_broker():
    """Check if MQTT broker is running"""
    print("🔍 Checking MQTT broker...")
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 1883))
        sock.close()
        
        if result == 0:
            print("✓ MQTT broker is running on localhost:1883")
            return True
        else:
            print("✗ MQTT broker not found on localhost:1883")
            print("  Start MQTT broker with: docker run -d -p 1883:1883 eclipse-mosquitto")
            return False
    except Exception as e:
        print(f"✗ Error checking MQTT: {e}")
        return False

def get_serial_port():
    """Get serial port from user or detect it"""
    print("\n📡 Serial Port Detection")
    print("=" * 50)
    
    if platform.system() == "Windows":
        import subprocess
        result = subprocess.run(['powershell', 'Get-SerialPort'], capture_output=True, text=True)
        if result.returncode == 0:
            print("Available ports:")
            print(result.stdout)
    else:
        os.system("ls -la /dev/tty* | grep -E 'USB|ACM'")
    
    port = input("\nEnter serial port (default: COM3): ").strip() or "COM3"
    return port

def get_mqtt_config():
    """Get MQTT configuration from user"""
    print("\n🔧 MQTT Configuration")
    print("=" * 50)
    
    mqtt_host = input("MQTT Host (default: localhost): ").strip() or "localhost"
    mqtt_port = input("MQTT Port (default: 1883): ").strip() or "1883"
    group_id = input("Group ID (default: group25): ").strip() or "group25"
    project_id = input("Project ID (default: peak): ").strip() or "peak"
    
    return {
        "MQTT_HOST": mqtt_host,
        "MQTT_PORT": mqtt_port,
        "GROUP_ID": group_id,
        "PROJECT_ID": project_id
    }

def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║     Peak Load Detection System - Real Sensor Setup         ║
║                    Group 25 - CO326                        ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Step 1: Install dependencies
    if not install_dependencies():
        sys.exit(1)
    
    # Step 2: Check MQTT
    if not check_mqtt_broker():
        print("\n⚠️  Continue anyway? (y/n): ", end="")
        if input().lower() != 'y':
            sys.exit(1)
    
    # Step 3: Get configuration
    serial_port = get_serial_port()
    mqtt_config = get_mqtt_config()
    use_real = input("\nUse real sensor data? (y/n, default: y): ").strip().lower()
    use_real_sensor = use_real != 'n'
    
    # Step 4: Set environment variables
    os.environ.update(mqtt_config)
    os.environ["SERIAL_PORT"] = serial_port
    os.environ["USE_REAL_SENSOR"] = "true" if use_real_sensor else "false"
    
    print("\n" + "=" * 50)
    print("Configuration Summary:")
    print("=" * 50)
    print(f"MQTT Host:        {mqtt_config['MQTT_HOST']}")
    print(f"MQTT Port:        {mqtt_config['MQTT_PORT']}")
    print(f"Serial Port:      {serial_port}")
    print(f"Use Real Sensor:  {use_real_sensor}")
    print(f"Group ID:         {mqtt_config['GROUP_ID']}")
    print(f"Project ID:       {mqtt_config['PROJECT_ID']}")
    print("=" * 50)
    
    # Step 5: Start publisher
    print("\n▶️  Starting MQTT Publisher...")
    print("-" * 50)
    print("Dashboard will be available at: http://localhost:1880/ui")
    print("Press Ctrl+C to stop")
    print("-" * 50 + "\n")
    
    try:
        subprocess.run([sys.executable, "mqtt_publisher.py"], check=False)
    except KeyboardInterrupt:
        print("\n\n✓ Publisher stopped")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
