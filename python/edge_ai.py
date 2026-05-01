"""
edge_ai.py — Peak Load Detection: Edge AI Inference Engine
===========================================================

Three complementary detectors are combined into an ensemble:

  1. Fixed Threshold   — flags any reading above PEAK_THRESHOLD_KW (600 kW).
                         Fast, interpretable, zero false-negatives for extreme spikes.

  2. Rolling Z-Score   — statistical process control. Flags a reading whose
                         Z-score relative to the last 50 readings exceeds 2.5.
                         Adapts to slowly drifting baselines.

  3. Isolation Forest  — unsupervised ML model pre-trained on normal load data.
                         Detects subtle multi-feature anomalies that threshold
                         and Z-score miss. Loaded lazily from disk at first use.

Ensemble policy (configurable):
  - "any"  (default) — peak if ANY detector triggers (minimises missed events)
  - "majority"       — peak if 2 or more detectors trigger (reduces false positives)
  - "all"            — peak if ALL detectors trigger (strictest)
"""

import logging
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from ml.feature_engineering import FeatureExtractor
from ml.anomaly_model import IsolationForestDetector, DEFAULT_MODEL_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------

PEAK_THRESHOLD_KW: float = float(os.environ.get("PEAK_THRESHOLD_KW", "600.0"))
ZSCORE_WINDOW: int = int(os.environ.get("ZSCORE_WINDOW", "100"))  # larger window dilutes peak influence
ZSCORE_THRESHOLD: float = float(os.environ.get("ZSCORE_THRESHOLD", "2.5"))
ENSEMBLE_POLICY: str = os.environ.get("ENSEMBLE_POLICY", "majority")   # any | majority | all
USE_ISOLATION_FOREST: bool = (
    os.environ.get("USE_ISOLATION_FOREST", "true").lower() == "true"
)


# ---------------------------------------------------------------------------
# Detector result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    """Detailed output from the peak detection ensemble."""

    # Final verdict
    is_peak: bool

    # Per-detector verdicts
    threshold_triggered: bool
    zscore_triggered: bool
    isolation_forest_triggered: bool

    # Quantitative signals
    power_kw: float
    zscore: Optional[float]            # None if not enough history
    if_anomaly_score: Optional[float]  # None if IF not loaded

    # Human-readable summary
    @property
    def reason(self) -> str:
        reasons: List[str] = []
        if self.threshold_triggered:
            reasons.append(f"threshold>{PEAK_THRESHOLD_KW:.0f}kW")
        if self.zscore_triggered:
            reasons.append(f"zscore>{ZSCORE_THRESHOLD:.1f}")
        if self.isolation_forest_triggered:
            reasons.append("isolation_forest")
        return "+".join(reasons) if reasons else "none"

    def to_dict(self) -> Dict:
        return {
            "is_peak": self.is_peak,
            "reason": self.reason,
            "power_kw": self.power_kw,
            "zscore": round(self.zscore, 4) if self.zscore is not None else None,
            "if_score": (
                round(self.if_anomaly_score, 4)
                if self.if_anomaly_score is not None
                else None
            ),
            "detectors": {
                "threshold": self.threshold_triggered,
                "zscore": self.zscore_triggered,
                "isolation_forest": self.isolation_forest_triggered,
            },
        }


# ---------------------------------------------------------------------------
# Module-level state (one shared instance per process)
# ---------------------------------------------------------------------------

_zscore_window: Deque[float] = deque(maxlen=ZSCORE_WINDOW)
_feature_extractor: FeatureExtractor = FeatureExtractor()
_if_detector: Optional[IsolationForestDetector] = None
_if_load_attempted: bool = False


def _load_if_detector() -> Optional[IsolationForestDetector]:
    """
    Lazy-load the Isolation Forest model.
    Returns None if the model file is not found (graceful degradation).
    """
    global _if_detector, _if_load_attempted
    if _if_load_attempted:
        return _if_detector
    _if_load_attempted = True
    if not USE_ISOLATION_FOREST:
        logger.info("[EdgeAI] Isolation Forest disabled via USE_ISOLATION_FOREST=false")
        return None
    try:
        _if_detector = IsolationForestDetector.load(DEFAULT_MODEL_PATH)
        logger.info("[EdgeAI] Isolation Forest model loaded successfully.")
    except FileNotFoundError:
        logger.warning(
            "[EdgeAI] Isolation Forest model not found at %s. "
            "Run `python train_model.py` to train it. "
            "System will use threshold + Z-score only.",
            DEFAULT_MODEL_PATH,
        )
        _if_detector = None
    return _if_detector


# ---------------------------------------------------------------------------
# Individual detectors
# ---------------------------------------------------------------------------

def detect_peak_threshold(power_kw: float) -> bool:
    """Return True if the reading exceeds the absolute fixed threshold."""
    return power_kw > PEAK_THRESHOLD_KW


def detect_peak_zscore(power_kw: float) -> Tuple[bool, Optional[float]]:
    """
    Return (is_peak, robust_zscore).

    Uses Median + MAD (Median Absolute Deviation) instead of mean + std.
    The median is unaffected by outliers (peaks), so even at 30% peak rate
    the baseline remains stable. MAD scaled by 1.4826 gives a consistent
    sigma-equivalent for Gaussian noise.

    Returns (False, None) if there is not enough history yet.
    """
    _zscore_window.append(power_kw)
    if len(_zscore_window) < 10:
        return False, None
    arr = np.array(_zscore_window, dtype=np.float64)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    # Scale factor 1.4826 makes MAD a consistent estimator of sigma for Gaussian data
    robust_std = 1.4826 * mad if mad > 0.0 else float(arr.std(ddof=0))
    if robust_std == 0.0:
        return False, 0.0
    z = (power_kw - median) / robust_std
    return z > ZSCORE_THRESHOLD, round(z, 4)


def detect_peak_isolation_forest(
    power_kw: float,
) -> Tuple[bool, Optional[float]]:
    """
    Return (is_anomaly, score).
    Extracts features and queries the Isolation Forest model.
    Returns (False, None) if the model is not available or not warmed up.
    """
    detector = _load_if_detector()
    feature_vec = _feature_extractor.update(power_kw)

    if detector is None:
        return False, None

    if not _feature_extractor.is_ready(min_readings=10):
        return False, None

    try:
        is_anomaly, score = detector.predict(feature_vec)
        return is_anomaly, score
    except Exception as exc:
        logger.error("[EdgeAI] IF inference error: %s", exc)
        return False, None


# ---------------------------------------------------------------------------
# Ensemble combiner
# ---------------------------------------------------------------------------

def _apply_policy(votes: List[bool], policy: str) -> bool:
    """Combine detector votes according to the ensemble policy."""
    n_triggered = sum(votes)
    if policy == "all":
        return n_triggered == len(votes)
    elif policy == "majority":
        return n_triggered > len(votes) / 2
    else:  # "any" (default)
        return n_triggered > 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_peak(power_kw: float) -> bool:
    """
    Simple boolean check — backward-compatible with existing callers.
    Returns True if the ensemble determines this reading is a peak.
    """
    return detect_peak_full(power_kw).is_peak


def detect_peak_full(power_kw: float) -> DetectionResult:
    """
    Full detection with per-detector explanations and scores.

    Args:
        power_kw: Current power reading in kilowatts.

    Returns:
        DetectionResult with verdict, per-detector flags, and scores.
    """
    # --- Run each detector ---
    thr_triggered = detect_peak_threshold(power_kw)
    zsc_triggered, zscore = detect_peak_zscore(power_kw)
    if_triggered, if_score = detect_peak_isolation_forest(power_kw)

    # --- Apply ensemble policy ---
    votes = [thr_triggered, zsc_triggered, if_triggered]
    is_peak = _apply_policy(votes, ENSEMBLE_POLICY)

    return DetectionResult(
        is_peak=is_peak,
        threshold_triggered=thr_triggered,
        zscore_triggered=zsc_triggered,
        isolation_forest_triggered=if_triggered,
        power_kw=power_kw,
        zscore=zscore,
        if_anomaly_score=if_score,
    )


def reset_state() -> None:
    """
    Reset all stateful components (window buffers, feature extractor).
    Useful between independent sessions or in unit tests.
    """
    global _if_load_attempted, _if_detector
    _zscore_window.clear()
    _feature_extractor.reset()
    _if_load_attempted = False
    _if_detector = None
