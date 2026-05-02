# Peak Load Detection System — Group 25

An **Edge AI–based IoT system** that detects peak industrial power demand in real-time using an **ESP32 sensor node**, **Python Edge AI inference**, and **dual dashboards** (Node-RED for real-time monitoring + Grafana for historical analysis). Built for the CO326 Edge AI + Industrial IoT mini-project framework.

**Key Features:**
- 🔌 **Real-time peak detection** using ensemble ML (Threshold + Z-Score + Isolation Forest)
- 📊 **Dual dashboards** — Node-RED UI for live monitoring, Grafana for trends
- 📡 **MQTT-based architecture** — Decoupled, scalable messaging
- ⚡ **No WiFi required** — Data flows via USB serial → Python → MQTT (local)
- 🔧 **Fully configurable** — thresholds, polling rates, detection algorithms

---

## System Architecture

### Data Flow
```
Hardware                 Local Processing              Visualization
─────────────────────   ──────────────────────────    ─────────────────

ESP32 (USB Serial) ──┐
  • ACS712 sensor    │
  • Demo mode        ├──→ Python Edge AI ──→ Local MQTT ──┬──→ Node-RED UI
  • LEDs + Relay     │    (run_standalone.py)             ├──→ Grafana DB
  • Local detection  │    • Read serial                    └──→ Mosquitto
└────────────────────┘    • Publish to MQTT

No WiFi needed! Python runs on your PC.
```

### Component Stack

| Layer | Component | Purpose | Technology |
|---|---|---|---|
| **Hardware** | ACS712 5A sensor | Measure AC current | ESP32 Dev Board |
| **Sensor** | Push button + Demo mode | Simulate peaks for testing | Arduino C++ |
| **Local Detection** | Threshold + Z-score | Fast peak detection on ESP32 | ESP32 firmware |
| **Edge AI** | Ensemble detector | Advanced peak detection | Python + scikit-learn |
| **Transport** | USB Serial + MQTT | Data flow from ESP32 to dashboards | Mosquitto broker |
| **Real-time UI** | Node-RED Dashboard | Live power gauge, alerts, relay control | Node-RED |
| **Historical** | InfluxDB + Grafana | Time-series storage & trend analysis | InfluxDB 2.x |

---

## Quick Start (5 minutes)

### Prerequisites

- **Hardware:** ESP32 Dev Board connected via USB
- **Software:** Python 3.10+, Docker, Docker Compose
- **Network:** Local MQTT broker (Mosquitto in Docker)

### Step 1: Prepare the ESP32

The ESP32 firmware is in demo mode by default (no WiFi required). To enable WiFi later:

1. Open [peak-load-detection/src/main.cpp](peak-load-detection/src/main.cpp#L27-L28)
2. Update WiFi credentials:
   ```cpp
   const char* WIFI_SSID     = "YourWiFiName";
   const char* WIFI_PASSWORD = "YourPassword";
   ```
3. Update MQTT broker IP:
   ```cpp
   const char* MQTT_BROKER = "10.163.16.53";  // Your PC's IP from ipconfig
   ```

Build and upload:
```powershell
cd peak-load-detection
pio run -t upload -e esp32dev
pio device monitor -b 115200  # Monitor serial output
```

**For now, leave it in demo mode** — just press buttons in the serial menu (A/N/W/P) to test.

### Step 2: Start Docker Services

```powershell
# In the project root directory
docker compose up
```

This starts:
- **Mosquitto MQTT** (port 1883) — message broker
- **Node-RED** (port 1880) — real-time dashboard
- **InfluxDB** (port 8086) — time-series database
- **Grafana** (port 3000) — historical dashboards

### Step 3: Install Python Dependencies

```powershell
cd python
pip install -r requirements.txt
```

Required packages:
- `paho-mqtt` — MQTT client
- `pyserial` — Serial communication
- `numpy`, `scikit-learn`, `joblib` — Machine learning

### Step 4: Run the Python Edge AI Bridge

```powershell
cd python

# Find your ESP32's COM port (if not COM5)
python find_port.py

# Set the port and MQTT broker
$env:SERIAL_PORT = "COM5"           # Change if different
$env:MQTT_HOST = "localhost"        # Local MQTT

# Run the bridge
python run_standalone.py
```

**What this does:**
- Reads sensor data from ESP32 serial (COM5)
- Runs peak detection (Threshold + Z-Score + Isolation Forest)
- Publishes to MQTT: `sensors/group25/peak/raw`

### Step 5: Access the Dashboards

| Dashboard | URL | Default Credentials |
|---|---|---|
| **Node-RED** (Real-time) | http://localhost:1880/ui | None required |
| **Grafana** (Historical) | http://localhost:3000 | admin / admin |
| **InfluxDB** (Data) | http://localhost:8086 | admin / admin12345 |

---

## Detailed Component Guide

### ESP32 Firmware

**Location:** [peak-load-detection/](peak-load-detection/)

**Hardware Layout:**
```
ACS712 (5A)  → GPIO34 (ADC)
Relay        → GPIO26 (active-LOW)
LED Green    → GPIO15
LED Yellow   → GPIO16
LED Red      → GPIO17
Button       → GPIO18 (INPUT_PULLUP)
```

**Operating Modes:**

| Mode | Setting | Behavior | WiFi |
|---|---|---|---|
| **AUTO** | `demoMode = 0` | Real sensor + MQTT | Required |
| **DEMO** | `demoMode = 1` | Simulated data (default) | Not needed |
| **NORMAL** | `demoMode = 2` | Force green LED | Not needed |
| **WARNING** | `demoMode = 3` | Force yellow LED | Not needed |
| **PEAK** | `demoMode = 4` | Force red + relay trip | Not needed |

Serial menu (when running):
```
A = AUTO mode       (use real sensor)
N = NORMAL          (force green LED)
W = WARNING         (force yellow LED)
P = PEAK            (force peak detection)
R = RELAY ON        (manually restore relay)
M = Show menu
```

### Python Edge AI

**Location:** [python/](python/)

**Main Scripts:**

| Script | Purpose | Usage |
|---|---|---|
| `run_standalone.py` | Read ESP32 serial → MQTT | `python run_standalone.py` |
| `debug_serial.py` | Show raw ESP32 output | `python debug_serial.py` (debug) |
| `find_port.py` | Detect ESP32 COM port | `python find_port.py` |
| `edge_ai.py` | Peak detection ensemble | Imported by run_standalone.py |

**Environment Variables:**

```powershell
$env:SERIAL_PORT = "COM5"              # ESP32 serial port
$env:MQTT_HOST = "localhost"           # MQTT broker (localhost or IP)
$env:MQTT_PORT = "1883"                # MQTT port
$env:GROUP_ID = "group25"              # Group identifier
$env:PROJECT_ID = "peak"               # Project name
```

### MQTT Topics

| Topic | Type | Frequency | Payload Example |
|---|---|---|---|
| `sensors/group25/peak/raw` | Publish | 1/sec | `{"power_w": 1.27, "state": "NORMAL", "timestamp": "..."}` |
| `commands/group25/peak/relay` | Subscribe | On-demand | `"ON"` or `"OFF"` |

### Edge AI Detection Algorithm

**Ensemble Approach:** Combines 3 detectors for high accuracy

1. **Fixed Threshold**
   - Triggers if: `power_w > 1.5 W`
   - Pros: Fast, no false negatives on extreme spikes
   - Cons: Fixed threshold, no adaptation

2. **Rolling Z-Score** (Statistical Control)
   - Compares current reading to last 100 samples
   - Triggers if: Z-score > 2.5
   - Pros: Adapts to baseline drift
   - Cons: Needs warmup period

3. **Isolation Forest** (Machine Learning)
   - Unsupervised anomaly detector
   - Pre-trained on normal load data
   - Pros: Catches subtle multi-feature anomalies
   - Cons: Requires ML model (lazy-loaded on first use)

**Configuration** (in [python/edge_ai.py](python/edge_ai.py#L43-L50)):
```python
PEAK_THRESHOLD_KW = 0.6           # Threshold detector (kW)
ZSCORE_WINDOW = 100               # Z-score window size
ZSCORE_THRESHOLD = 2.5            # Z-score cutoff
ENSEMBLE_POLICY = "majority"      # "any", "majority", or "all"
USE_ISOLATION_FOREST = True       # Enable ML detector
```

---

## Troubleshooting

### Issue: ESP32 won't connect to WiFi

**Symptoms:**
```
[WiFi] Connecting to YourWiFi...
[WiFi] Failed to connect — continuing without WiFi.
```

**Solutions:**
1. **Check WiFi band** — ESP32 only supports 2.4GHz. Run on your PC:
   ```powershell
   netsh wlan show networks mode=Bssid | findstr "Band"
   ```
   If it shows `5 GHz`, enable 2.4GHz in your WiFi router/hotspot settings.

2. **Verify credentials** — Double-check SSID and password in main.cpp

3. **Use demo mode** — Keep `demoMode = 1` and skip WiFi entirely

### Issue: Python can't find ESP32 serial port

**Solutions:**
```powershell
# Find available ports
python find_port.py

# Set the correct port
$env:SERIAL_PORT = "COM3"  # Change to detected port
python run_standalone.py
```

### Issue: MQTT messages not appearing

**Check MQTT is running:**
```powershell
docker ps | findstr mosquitto
netstat -an | findstr :1883
```

**Test MQTT directly:**
```powershell
# In one window:
docker run -d -p 1883:1883 eclipse-mosquitto

# In another:
mosquitto_sub -h localhost -t "sensors/#" -v
```

**Common fixes:**
- Restart Docker: `docker restart <container_id>`
- Check Python script output for errors
- Verify `$env:MQTT_HOST` is set correctly

### Issue: Node-RED dashboard shows no data

**Checklist:**
1. ✅ MQTT broker running (`docker ps`)
2. ✅ Python script publishing (`mosquitto_sub -h localhost -t sensors/#`)
3. ✅ Node-RED can see messages (check MQTT input nodes)
4. ✅ Dashboard flows are imported

**Debug:**
```powershell
# Monitor all MQTT messages
mosquitto_sub -h localhost -t "#" -v

# Check what topics are being published
mosquitto_sub -h localhost -t "sensors/group25/peak/#" -v
```

### Issue: Data publishing too slow

**Causes:**
- `edge_ai.detect_peak()` loads ML model on first run (1-2 seconds)
- Serial timeout set to 1 second
- MQTT publish delay

**Solutions:**
```python
# In run_standalone.py, reduce sleep time:
time.sleep(0.1)  # Was 0.1, reduce to 0.01 for faster reads

# Or disable edge_ai processing:
# detection = None  # Skip detection to speed up
```

---

## Useful Commands

```powershell
# Monitor ESP32 serial output
pio device monitor -b 115200

# Check all MQTT messages
mosquitto_sub -h localhost -t "#" -v

# List Docker containers
docker ps

# View Docker logs
docker logs group25-mqtt-broker
docker logs group25-edge-ai

# Test Python script without ESP32
python test_mqtt_only.py

# Kill all Docker containers
docker stop $(docker ps -q)
```

---

## Support & Contact

### Common Questions

**Q: Do I need WiFi on the ESP32?**  
A: No! WiFi is optional. Data flows via USB serial to Python → MQTT. Use demo mode if WiFi fails.

**Q: How often does it publish data?**  
A: ESP32 sends ~1 sample/second via serial. Python reads and publishes to MQTT immediately.

**Q: Can I use a different MQTT broker?**  
A: Yes! Set `$env:MQTT_HOST = "broker.hivemq.com"` (cloud) or your broker IP.

**Q: How do I add custom detection algorithms?**  
A: Edit [python/edge_ai.py](python/edge_ai.py) — add detectors to the ensemble.

---

## Documentation

- **[Project Report](docs/report/)** — Full technical documentation, system design, test results, and analysis

---

## Team

- E/20/439, J.M.W.G.R.L. Wickrmasinghe, [email](mailto:e20439@eng.pdn.ac.lk)
- E/20/419, M.M.S.S. Wakkumbura, [email](mailto:e20419@eng.pdn.ac.lk)
- E/20/244, P. Malshan, [email](mailto:e20244@eng.pdn.ac.lk)

---

## Links

- [Project Repository](https://github.com/cepdnaclk/e20-co326-Peak-Load-Detection-System)
- [Department of Computer Engineering](http://www.ce.pdn.ac.lk/)
- [University of Peradeniya](https://eng.pdn.ac.lk/)
