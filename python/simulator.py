import numpy as np
import time
from typing import Dict


def generate_load_reading(t_seconds: float) -> float:
    """
    Simulate industrial power usage.
    - Base: sinusoidal daily pattern (low at night, high in working hours)
    - Noise: Gaussian measurement noise
    - Peaks: occasional spikes representing peak demand events
    """
    # 24h period in seconds
    day_period = 24 * 60 * 60

    # Baseline around 300 kW with ±100 kW variation over the day
    base = 300.0 + 100.0 * np.sin(2 * np.pi * (t_seconds % day_period) / day_period)

    # Random noise
    noise = np.random.normal(0.0, 20.0)
    load = base + noise

    # Inject peaks ~10% of the time
    if np.random.random() < 0.10:
        load += np.random.uniform(300.0, 500.0)

    # Ensure non-negative
    load = max(load, 0.0)
    return round(load, 2)


def get_sensor_payload(start_time: float, step_index: int) -> Dict:
    """Return a JSON-serializable payload for the current reading."""
    now = start_time + step_index * 5  # assume 5 s per step in simulation time
    load = generate_load_reading(now)
    timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    payload = {
        "timestamp": timestamp_str,
        "power_kw": load,
        "group": "group25",
        "project": "peak-load",
        "mode": "normal",
    }
    return payload


if __name__ == "__main__":
    # Simple test run
    t0 = time.time()
    for i in range(5):
        print(get_sensor_payload(t0, i))
        time.sleep(1)
