# Peak Load Detection System — Group 25

An Edge AI–based IoT system that detects peak power demand using an ESP32
sensor node, Python Edge AI inference, and dual dashboards (Node-RED real-time +
Grafana historical). Built for the CO326 Edge AI + Industrial IoT mini-project.

---

## System Architecture

```
ESP32 (USB Serial)                     Docker Containers
┌─────────────────┐                    ┌─────────────────────────┐
│  ACS712 Sensor   │                   │  Mosquitto MQTT (:1883) │
│  Push Button     │──── Serial ───►   │  Node-RED      (:1880)  │
│  LEDs + Relay    │                   │  InfluxDB      (:8086)  │
│  Local Detection │                   │  Grafana       (:3000)  │
└─────────────────┘                    └─────────────────────────┘
                        ▲
                        │
               ┌────────┴────────┐
               │  Python Edge AI  │  ← Runs on host PC
               │  (Serial Reader) │     reads serial, publishes
               │  (MQTT Publisher)│     to MQTT + InfluxDB
               │  (InfluxDB Writer│
               └─────────────────┘
```

| Layer | Component | Technology |
|---|---|---|
| Perception | ACS712 current sensor + push button | ESP32, Arduino |
| Edge Logic | Local threshold + Z-score detection | ESP32 (C++) |
| Edge AI | Ensemble: Threshold + Z-Score + Isolation Forest | Python, scikit-learn |
| Transport | Serial USB + MQTT | pyserial, paho-mqtt, Mosquitto |
| Visualization | Real-time dashboard | Node-RED |
| Historical | Time-series storage + dashboards | InfluxDB 2.x + Grafana |

---

## How to Run

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Python 3.10+ with pip
- ESP32 connected via USB (COM5)

### 1. Clone and configure

```bash
git clone https://github.com/cepdnaclk/e20-co326-Peak-Load-Detection-System.git
cd e20-co326-Peak-Load-Detection-System
```

### 2. Start Docker infrastructure

```bash
docker compose up
```

This starts 4 containers: Mosquitto, Node-RED, InfluxDB, Grafana.

### 3. Install Python dependencies and run the bridge

```bash
cd python
pip install -r requirements.txt
python mqtt_publisher.py
```

### 4. Access dashboards

| Dashboard | URL | Purpose |
|---|---|---|
| Node-RED | http://localhost:1880/ui | Real-time power gauge, chart, alerts |
| Grafana | http://localhost:3000 | Historical analytics (admin/admin) |
| InfluxDB | http://localhost:8086 | Raw data explorer (admin/admin12345) |

---

## MQTT Topics

| Topic | Description |
|---|---|
| `sensors/group25/peak/data` | Processed sensor readings with status |
| `alerts/group25/peak/status` | Peak detection alert events |

---

## Edge AI Detection

Three ensemble detectors in `python/edge_ai.py`:

1. **Fixed Threshold** — power_w > 1.5 W
2. **Rolling Z-Score** — MAD-based robust z-score > 2.5
3. **Isolation Forest** — unsupervised ML (scikit-learn)

Policy: `any` — peak if ANY detector triggers.

---

## Team

- E/20/XXX, Member 1, [email](mailto:member1@eng.pdn.ac.lk)
- E/20/XXX, Member 2, [email](mailto:member2@eng.pdn.ac.lk)
- E/20/XXX, Member 3, [email](mailto:member3@eng.pdn.ac.lk)

---

## Links

- [Project Repository](https://github.com/cepdnaclk/e20-co326-Peak-Load-Detection-System)
- [Department of Computer Engineering](http://www.ce.pdn.ac.lk/)
- [University of Peradeniya](https://eng.pdn.ac.lk/)
