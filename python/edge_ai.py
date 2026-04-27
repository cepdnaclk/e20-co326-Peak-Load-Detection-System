from collections import deque
from typing import Deque

import numpy as np

# Fixed threshold (kW) for absolute peak
PEAK_THRESHOLD_KW = 600.0

# Rolling window for Z-score detection
WINDOW_SIZE = 50

_window: Deque[float] = deque(maxlen=WINDOW_SIZE)


def detect_peak_threshold(power_kw: float) -> bool:
    """Return True if the reading exceeds the absolute threshold."""
    return power_kw > PEAK_THRESHOLD_KW


def detect_peak_zscore(power_kw: float) -> bool:
    """Return True if the reading is a statistical outlier (high Z-score)."""
    _window.append(power_kw)
    if len(_window) < 10:
        # Not enough history yet
        return False
    mean = float(np.mean(_window))
    std = float(np.std(_window))
    if std == 0.0:
        return False
    z = (power_kw - mean) / std
    return z > 2.5


def detect_peak(power_kw: float) -> bool:
    """Combined decision: peak if either detector triggers."""
    return detect_peak_threshold(power_kw) or detect_peak_zscore(power_kw)
