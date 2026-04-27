# Peak Load Detection System — Group 25

An Edge AI–based IoT system that simulates industrial power load data and detects peak
demand periods. The system publishes data and alerts via MQTT and visualizes them using
a Node-RED dashboard, fully aligned with the CO326 Edge AI + Industrial IoT mini-project
framework.

---

## System Architecture

```
Sensor/Data Simulator → Edge AI (Python) → MQTT Broker → Node-RED → Dashboard
```

| Layer | Component | Technology |
|---|---|---|
| Perception | Power load simulator | Python, NumPy |
| Transport | MQTT client / broker | paho-mqtt |
| Edge Logic | Peak detection (threshold + Z-score) | Python |
| Application | Real-time dashboard | Node-RED |

---

## Repository Structure

```
.
├── python/
│   ├── simulator.py        # Industrial power load data generator
│   ├── edge_ai.py          # Peak detection logic (threshold + Z-score)
│   ├── mqtt_publisher.py   # MQTT client publishing data & alerts
│   ├── requirements.txt    # Python dependencies
│   └── Dockerfile          # Container for the Python service
├── node-red/
│   └── flows.json          # Node-RED dashboard flows
├── docs/                   # Project report and documentation
├── docker-compose.yml      # Orchestrates the edge-AI service
└── README.md
```

---

## How to Run

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Access to an MQTT broker (instructor-provided or local Mosquitto)

### 1. Clone the repository

```bash
git clone https://github.com/cepdnaclk/e20-co326-Peak-Load-Detection-System.git
cd e20-co326-Peak-Load-Detection-System
```

### 2. Configure the MQTT broker

Set the broker host via an environment variable (or edit `docker-compose.yml`):

```bash
export MQTT_HOST=<broker-hostname-or-ip>
export MQTT_PORT=1883          # default
```

### 3. Start the edge-AI service

```bash
docker-compose up --build
```

The container will start publishing power-load readings every 2 seconds.

### 4. Import Node-RED flows

1. Open the Node-RED editor (provided by the course environment).
2. Click **☰ → Import → Clipboard**.
3. Paste the contents of `node-red/flows.json` and click **Import**.
4. Update the `mqtt-broker-config` node with the broker address.
5. Deploy and open the dashboard at `http://<nodered-host>:1880/ui`.

---

## MQTT Topics

| Topic | Description | Direction |
|---|---|---|
| `sensors/group25/peak/data` | Power load readings (kW) | Publisher → Broker |
| `alerts/group25/peak/status` | Peak detection alerts | Publisher → Broker |

### Data payload example

```json
{
  "timestamp": "2026-04-23T12:34:56",
  "power_kw": 523.75,
  "group": "group25",
  "project": "peak-load",
  "mode": "normal"
}
```

### Alert payload example

```json
{
  "timestamp": "2026-04-23T12:34:56",
  "power_kw": 812.40,
  "status": "PEAK_DETECTED",
  "reason": "threshold_or_zscore",
  "group": "group25",
  "project": "peak-load"
}
```

---

## Edge AI Detection Logic

Two complementary detection methods are implemented in `python/edge_ai.py`:

1. **Fixed Threshold** — flags any reading above 600 kW as a peak (configurable via
   `PEAK_THRESHOLD_KW`).
2. **Rolling Z-Score** — maintains a sliding window of the last 50 readings; flags a
   reading whose Z-score exceeds 2.5 as an anomalous spike.

A reading is treated as a peak if **either** detector triggers, minimising missed events.

---

## Dashboard

The Node-RED dashboard (`node-red/flows.json`) provides:

- **Line Chart** — real-time `power_kw` time series from `sensors/group25/peak/data`
- **Gauge** — current load with 0–900 kW range
- **Alert Text Panel** — live alerts from `alerts/group25/peak/status`

---

## Team

- E/20/XXX, Member 1, [email](mailto:member1@eng.pdn.ac.lk)
- E/20/XXX, Member 2, [email](mailto:member2@eng.pdn.ac.lk)
- E/20/XXX, Member 3, [email](mailto:member3@eng.pdn.ac.lk)

---

## Challenges and Future Work

- Tuning the fixed threshold and Z-score window size for production load profiles.
- Integrating a real smart-meter data feed instead of the simulator.
- Exploring more advanced anomaly detection models (e.g., Isolation Forest) as an
  optional extension.

---

## Links

- [Project Repository](https://github.com/cepdnaclk/e20-co326-Peak-Load-Detection-System)
- [Department of Computer Engineering](http://www.ce.pdn.ac.lk/)
- [University of Peradeniya](https://eng.pdn.ac.lk/)
