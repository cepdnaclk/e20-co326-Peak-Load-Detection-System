"""
Feature engineering for Peak Load Detection System.

Extracts a rich set of ROBUST statistical and temporal features from a rolling
window of power readings. All rolling statistics use Median and MAD (Median
Absolute Deviation) instead of mean and std-dev, making them immune to
outlier contamination — a spike in the window does NOT shift the median or
MAD of the surrounding normal readings. This prevents the Isolation Forest
from seeing false-anomalous feature vectors for normal readings adjacent to peaks.

Feature vector (11 features):
  0  power_kw            – current raw reading (kW)
  1  rolling_median_10   – robust short-window median  (10 readings)
  2  rolling_mad_10      – robust short-window MAD     (10 readings)
  3  rolling_median_30   – robust medium-window median (30 readings)
  4  rolling_mad_30      – robust medium-window MAD    (30 readings)
  5  rolling_median_50   – robust long-window median   (50 readings)
  6  rolling_mad_50      – robust long-window MAD      (50 readings)
  7  rolling_max_50      – long-window maximum
  8  robust_zscore_50    – (power_kw - median_50) / (1.4826 * mad_50)
  9  delta               – first-order difference (change from last reading)
  10 ema_alpha03         – exponential moving average (alpha=0.3)
"""

from collections import deque
from typing import Optional
import numpy as np


WINDOW_SIZES = (10, 30, 50)
MAX_WINDOW = max(WINDOW_SIZES)
EMA_ALPHA = 0.3
FEATURE_NAMES = [
    "power_kw",
    "rolling_median_10",
    "rolling_mad_10",
    "rolling_median_30",
    "rolling_mad_30",
    "rolling_median_50",
    "rolling_mad_50",
    "rolling_max_50",
    "robust_zscore_50",
    "delta",
    "ema_alpha03",
]
N_FEATURES = len(FEATURE_NAMES)


class FeatureExtractor:
    """
    Stateful online feature extractor.

    Maintains a rolling window of the last MAX_WINDOW (50) readings and
    computes multi-scale statistical features for each new sample.
    Thread-safe usage: create one instance per data stream.
    """

    def __init__(self) -> None:
        self._window: deque[float] = deque(maxlen=MAX_WINDOW)
        self._ema: Optional[float] = None
        self._prev: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, power_kw: float) -> np.ndarray:
        """
        Consume one power reading and return a 1-D feature vector.

        All rolling statistics use Median + MAD so a peak inside the window
        does NOT corrupt the feature vector of surrounding normal readings.
        The vector will contain NaN values for statistics that cannot yet be
        computed (insufficient history). Check ``is_ready()`` before classifying.

        Args:
            power_kw: Latest power reading in kilowatts.

        Returns:
            np.ndarray of shape (N_FEATURES,) with dtype float64.
        """
        # --- update rolling buffer ---
        self._window.append(power_kw)

        # --- EMA ---
        if self._ema is None:
            self._ema = power_kw
        else:
            self._ema = EMA_ALPHA * power_kw + (1 - EMA_ALPHA) * self._ema

        # --- first difference ---
        delta = (power_kw - self._prev) if self._prev is not None else 0.0
        self._prev = power_kw

        arr = np.array(self._window, dtype=np.float64)

        # --- robust rolling stats (median + MAD) per window ---
        def _robust_stats(w: int):
            """Return (median, mad) for the last w readings; NaN if insufficient."""
            if len(arr) < w:
                return np.nan, np.nan
            sub = arr[-w:]
            median = float(np.median(sub))
            mad = float(np.median(np.abs(sub - median)))
            return median, mad

        med10, mad10 = _robust_stats(10)
        med30, mad30 = _robust_stats(30)
        med50, mad50 = _robust_stats(50)
        max50 = float(arr.max()) if len(arr) >= 50 else np.nan

        # --- Robust Z-score relative to 50-window (median + MAD-sigma) ---
        # 1.4826 converts MAD to a sigma-consistent estimator for Gaussian noise.
        if len(arr) >= 10 and mad50 > 0.0:
            robust_zscore = (power_kw - med50) / (1.4826 * mad50)
        elif len(arr) >= 10:
            robust_zscore = 0.0
        else:
            robust_zscore = np.nan

        return np.array(
            [
                power_kw,
                med10,  mad10,
                med30,  mad30,
                med50,  mad50,
                max50,
                robust_zscore,
                delta,
                self._ema,
            ],
            dtype=np.float64,
        )

    def is_ready(self, min_readings: int = 10) -> bool:
        """Return True once enough history exists for meaningful features."""
        return len(self._window) >= min_readings

    def reset(self) -> None:
        """Clear internal state (useful between independent sessions)."""
        self._window.clear()
        self._ema = None
        self._prev = None

    @property
    def history_len(self) -> int:
        """Number of readings stored in the rolling buffer."""
        return len(self._window)
