# Goal Description

The goal is to upgrade the current Peak Load Detection System to a production-ready edge AI architecture modeled after the "Motor Thermal Monitoring Digital Twin." This involves expanding the existing 3-container stack to a 7-container stack to support interchangeable Machine Learning (ML) classification algorithms, a decoupled predictive maintenance service, time-series data storage, and a digital twin visualization dashboard.

## User Review Required

> [!IMPORTANT]
> The architecture will be expanded significantly from 3 to 7 containers. Ensure your system has sufficient resources (Docker memory) to run InfluxDB and Grafana alongside the existing stack.

## Open Questions

> [!WARNING]
> 1. **Synthetic Data**: For the supervised ML models (Decision Tree, Random Forest, LSTM), I will need to generate synthetic training data based on your peak load thresholds (`PEAK_THRESHOLD_W = 1.5`, `WARNING_THRESHOLD_W = 1.125`). Should I write a generation script to simulate typical office/industrial load patterns with intermittent spikes for this purpose?
> 2. **Node-RED Flows**: I will add new nodes to integrate the predictive service and write data to InfluxDB. I plan to place these in a separate `flows-predict.json` to prevent merge conflicts with your existing HMI. Does this approach work for you?
> 3. **Hardware Constraints**: Are there any modifications needed on the `peak-load-detection` (ESP32) C++ code to support the `AUTO/MANUAL` mode, or is it sufficient to handle the mode entirely within the Python Edge AI module?

## Proposed Changes

---

### Infrastructure Layer

Expand the Docker Compose stack to support the full Digital Twin architecture.

#### [MODIFY] [docker-compose.yml](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/docker-compose.yml)
- Add `influxdb` service for time-series storage (with auto-provisioning tokens).
- Add `grafana` service for digital twin dashboards.
- Add `python-predict` service for the predictive maintenance layer.
- Add `python-device` service under a `simulation` profile to allow testing without physical ESP32 hardware.
- Rename `edge-ai` directory/service to `python-edge` to align with the proposed architecture.

---

### Reactive Edge AI (python-edge)

Refactor the existing Edge AI bridge to support a swappable ML algorithm interface, hysteresis fan/relay control, and AUTO/MANUAL operational modes.

#### [NEW] [python/ml/base.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python/ml/base.py)
- Shared feature engineering (power_w, z_score, delta, rolling_mean, rolling_std).

#### [NEW] [python/ml/z_score.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python/ml/z_score.py)
- Refactored version of the current baseline Z-score detection logic adhering to the new `load_model()` and `classify(data, window)` contract.

#### [NEW] [python/ml/decision_tree.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python/ml/decision_tree.py)
- Implementation of the Decision Tree classification algorithm.

#### [NEW] [python/ml/isolation_forest.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python/ml/isolation_forest.py)
- Implementation of the unsupervised Isolation Forest with rolling buffer auto-calibration.

#### [NEW] [python/ml/random_forest.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python/ml/random_forest.py)
- Implementation of the Random Forest algorithm with adjustable probability thresholds.

#### [MODIFY] [python/edge_ai.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python/edge_ai.py) & [python/esp32_bridge.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python/esp32_bridge.py)
- Integrate the swappable model registry (defaulting to Z-score).
- Add relay hysteresis control (wait for N consecutive NORMAL readings before restoring power).
- Implement response to `AUTO`/`MANUAL` mode topics.

---

### Predictive Maintenance Service (python-predict)

Introduce an independent, decoupled predictive AI layer to anticipate load peaks before they occur.

#### [NEW] [python-predict/Dockerfile](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python-predict/Dockerfile)
- Setup for the predictive container (using `tflite-runtime` if possible to save space).

#### [NEW] [python-predict/predictive_service.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python-predict/predictive_service.py)
- Subscribes to `sensors/group25/peak/data` (read-only).
- Publishes predictive risk scores and ETA to `predict/group25/peak/risk`.

#### [NEW] [python-predict/models/baseline_model.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python-predict/models/baseline_model.py)
- Linear slope extrapolation model to estimate ETA to `WARNING_THRESHOLD_W`.

#### [NEW] [python-predict/models/lstm_model.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python-predict/models/lstm_model.py)
- LSTM inference logic and architecture structure.

#### [NEW] [python-predict/train_lstm.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python-predict/train_lstm.py)
- Offline script to generate synthetic temporal data and train the `.keras` model locally.

---

### Software Simulator (python-device)

#### [NEW] [python-device/Dockerfile](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python-device/Dockerfile) & [python-device/mqtt_publisher.py](file:///f:/CO326-Nov2025-Computer-Systems-Engineering-Industrial-Networks/e20-co326-Peak-Load-Detection-System/python-device/mqtt_publisher.py)
- Emulates the ESP32 power readings with simulated load variations, spontaneous peaks, and responds to relay commands to complete the feedback loop.

## Verification Plan

### Automated Tests
- Run `python-device` simulator offline (using `docker compose --profile simulation up`) and observe predictive risk crossing thresholds prior to the edge AI.
- Train the Decision Tree and Random Forest models via an offline script, verifying the generated model weights fit in standard environments.

### Manual Verification
- Deploy to Node-RED and observe InfluxDB/Grafana metrics being populated with `risk_score`, `power_w`, and `status`.
- Manually toggle between `AUTO` and `MANUAL` via Node-RED to confirm the Edge AI stops issuing relay commands while continuing to log anomalies.
