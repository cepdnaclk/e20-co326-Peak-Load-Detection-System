# Real Sensor Data Integration Guide

## Overview

This guide walks you through connecting your real ESP32 sensor to the Node-RED dashboard via MQTT.

## System Architecture

```
ESP32 (ACS712 Sensor)
    ↓ (Serial/USB)
Python MQTT Publisher
    ↓ (MQTT over TCP)
MQTT Broker (localhost:1883)
    ↓ (MQTT subscribe)
Node-RED Dashboard
```

## Prerequisites

- **ESP32 device** with ACS712 current sensor (already configured in `main.cpp`)
- **MQTT Broker** running (Mosquitto or similar on localhost:1883)
- **Python 3.7+** with required packages
- **Node-RED** running with Dashboard addon

## Setup Steps

### 1. Install Python Dependencies

```bash
cd python
pip install paho-mqtt pyserial
```

### 2. Upload Code to ESP32

```bash
cd peak-load-detection
platformio run --target upload
```

Wait for upload to complete. You should see output like:
```
[POWER] Power: 2.45 W | State: NORMAL | Relay: ON
```

### 3. Identify Serial Port

- **Windows**: Check Device Manager → Ports (COM3, COM4, etc.)
- **Linux**: `ls /dev/ttyUSB*` or `ls /dev/ttyACM*`
- **macOS**: `ls /dev/tty.usbserial*`

### 4. Start MQTT Broker

```bash
# Mosquitto (if installed)
mosquitto

# Or via Docker
docker run -d -p 1883:1883 eclipse-mosquitto
```

### 5. Run Python Publisher with Real Sensor

**Option A: Real Sensor Data (USB Connected)**

```bash
cd python
export SERIAL_PORT=COM3  # Change to your port
export USE_REAL_SENSOR=true
python mqtt_publisher.py
```

**Option B: Simulated Data (for testing without device)**

```bash
cd python
python mqtt_publisher.py
```

You should see output like:
```
[DATA] {'timestamp': '2024-04-30T12:34:56', 'power_kw': 0.245, 'power_w': 245.2, 'state': 'NORMAL', 'is_peak': False, ...}
```

### 6. Import Flows into Node-RED

1. Open Node-RED at `http://localhost:1880`
2. Menu → Import → Select `node-red/flows.json`
3. Click "Import" → "New Flow"
4. Deploy

### 7. View Dashboard

Open `http://localhost:1880/ui` in your browser

## Dashboard Widgets

Your Node-RED dashboard now includes:

### Real-Time Monitor Group
- **Current Load (Gauge)**: Displays current power consumption in kW
  - Color coded: Green (normal) → Yellow (warning) → Red (peak)
  - Range: 0-1000 kW with segments at 300 kW and 600 kW
- **Fan Status (Text)**: Shows 🟢 FAN RUNNING or 🔴 FAN OFF
- **System Status (Text)**: Displays ✓ NORMAL, ⚡ WARNING, or ⚠ PEAK DETECTED

### Load History Group
- **Power Load History (Chart)**: Time-series line graph
  - Shows last 30 minutes of data
  - Displays both normal and peak states
  - Updates every ~1-2 seconds

### Alerts & Status Group
- **Latest Alert (Text)**: Shows peak detection alerts with timestamp and power

## MQTT Topics

The system publishes to these topics:

| Topic | Description | Payload |
|-------|-------------|---------|
| `sensors/group25/peak/data` | Sensor readings | `{timestamp, power_kw, power_w, state, is_peak}` |
| `alerts/group25/peak/status` | Peak alerts | `{timestamp, power_kw, power_w, status, reason}` |

## Configuration via Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_HOST` | localhost | MQTT broker address |
| `MQTT_PORT` | 1883 | MQTT broker port |
| `SERIAL_PORT` | COM3 | ESP32 serial port |
| `USE_REAL_SENSOR` | false | Set to `true` to read real sensor data |
| `PUBLISH_INTERVAL` | 1 | Seconds between MQTT publishes |
| `GROUP_ID` | group25 | Your group ID |
| `PROJECT_ID` | peak | Project identifier |

### Example: Using Environment Variables

```bash
# Linux/macOS
export MQTT_HOST=192.168.1.100
export SERIAL_PORT=/dev/ttyUSB0
export USE_REAL_SENSOR=true
python mqtt_publisher.py

# Windows PowerShell
$env:MQTT_HOST="192.168.1.100"
$env:SERIAL_PORT="COM3"
$env:USE_REAL_SENSOR="true"
python mqtt_publisher.py
```

## Troubleshooting

### Serial Connection Issues

**Problem**: "Failed to connect to sensor"

**Solutions**:
1. Check serial port in Device Manager (Windows) or with `ls /dev/tty*`
2. Update `SERIAL_PORT` environment variable
3. Try a different USB port/cable
4. Reset ESP32 (press RST button)
5. Check baud rate matches platformio.ini (115200)

### No Data in Dashboard

**Problem**: MQTT is running but dashboard shows no data

**Solutions**:
1. Verify MQTT broker is running: `mosquitto_sub -t "sensors/group25/peak/#"`
2. Check Python publisher output (should show `[DATA]` messages)
3. Restart Node-RED
4. Click "Deploy" in Node-RED editor
5. Check MQTT broker address in flows.json (`mqtt-broker-config`)

### Wrong Power Values

**Problem**: Power readings are very high or very low

**Solutions**:
1. Check ACS712 sensor wiring (pin 34 for analog input)
2. Verify SUPPLY_VOLTAGE constant in main.cpp (should be 5.0V)
3. Check sensor is connected to AC line properly
4. Try demo modes in ESP32 (press 'N', 'W', 'P' in serial monitor)

## Demo Modes (ESP32)

Open serial monitor to the ESP32 and press keys to test:

- `A` = AUTO (real sensor data)
- `N` = NORMAL (force green LED, fan running)
- `W` = WARNING (force yellow LED, ~75% threshold)
- `P` = PEAK (force red LED, relay off, fan stops)
- `R` = RELAY ON (manually restore)
- `M` = Show menu

## Peak Detection Algorithm

Peaks are detected using TWO methods (either triggers peak):

1. **Threshold**: Power > 1.5W (configurable as `PEAK_THRESHOLD_W`)
2. **Z-Score**: Statistical anomaly (>2.5 standard deviations from mean)

In Python (`edge_ai.py`):
- Threshold: Power > 600 kW
- Z-Score: 50-sample rolling window

## Data Flow

```
1. ESP32 reads ACS712 sensor (100 samples, every 2 seconds)
2. Calculates current (amps) → power (watts)
3. Checks both detection methods
4. Outputs: "[POWER] Power: 245.20 W | State: NORMAL | Relay: ON"
5. Python reads serial line
6. Parses and formats JSON payload
7. Publishes to MQTT broker
8. Node-RED subscribes, processes, displays
9. Dashboard updates in real-time
```

## Docker Deployment (Optional)

If running the entire system in Docker:

```bash
# Build and run containers
docker-compose up -d

# Logs
docker-compose logs -f python
docker-compose logs -f nodered
```

The `docker-compose.yml` already includes the correct environment variables.

## Next Steps

1. **Calibration**: Adjust `PEAK_THRESHOLD_W` in main.cpp if peaks aren't detected correctly
2. **Alerting**: Add email/SMS notifications in Node-RED for peak detection
3. **Historical Data**: Store readings in InfluxDB or similar for analysis
4. **REST API**: Add HTTP endpoints to query current power/status
5. **Mobile Dashboard**: Deploy Node-RED UI to mobile app
