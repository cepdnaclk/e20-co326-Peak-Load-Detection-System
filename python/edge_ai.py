from collections import deque
from typing import Deque

import numpy as np

# ---- Thresholds (Watts) ----
PEAK_THRESHOLD_W    = 1.5   # Trip relay when power exceeds this
WARNING_THRESHOLD_W = 1.3   # Show WARNING when power exceeds this
#
# Normal fan operating range is ~1.0–1.25W.
# WARNING at 1.3W only fires when the button ramp is actively pushing
# power toward the 1.5W peak — a genuinely meaningful alert.

# ---- Z-score anomaly detection ----
WINDOW_SIZE   = 50
ZSCORE_CUTOFF = 2.5

_window: Deque[float] = deque(maxlen=WINDOW_SIZE)


def detect_peak_threshold(power_w: float) -> bool:
    """Return True if the reading exceeds the absolute PEAK threshold."""
    return power_w > PEAK_THRESHOLD_W


def detect_peak_zscore(power_w: float) -> bool:
    """Return True if the reading is a statistical outlier (high Z-score)."""
    _window.append(power_w)
    if len(_window) < 10:
        return False
    mean = float(np.mean(_window))
    std  = float(np.std(_window))
    if std == 0.0:
        return False
    z = (power_w - mean) / std
    return z > ZSCORE_CUTOFF


def detect_peak(power_w: float) -> tuple:
    """
    Combined peak + warning detection.
    Returns: (is_peak: bool, state: str, is_warning: bool)
    """
    threshold_triggered = detect_peak_threshold(power_w)
    zscore_triggered    = detect_peak_zscore(power_w)
    is_peak   = threshold_triggered or zscore_triggered
    is_warning = (power_w > WARNING_THRESHOLD_W) and not is_peak

    if threshold_triggered and zscore_triggered:
        state = "THRESHOLD + Z-SCORE"
    elif threshold_triggered:
        state = "THRESHOLD"
    elif zscore_triggered:
        state = "Z-SCORE"
    elif is_warning:
        state = "WARNING"
    else:
        state = "NORMAL"

    return is_peak, state, is_warning
