#!/usr/bin/env python3
"""
evaluate_model.py — Standalone Evaluation Script
=================================================

Loads the saved Isolation Forest model and evaluates all three detectors
across a range of conditions:

  1. Balanced test set (10% peak injection)
  2. Rare-event set  (2% peak injection) — tests false negative rate
  3. Heavy-peak set  (30% peak injection) — tests false positive rate

Reports:
  - Confusion matrix values (TP, FP, TN, FN)
  - Precision, Recall, F1 Score, Accuracy
  - Saves results to ml/evaluation_report.json

Usage (from python/ directory):
    python evaluate_model.py
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from ml.feature_engineering import FeatureExtractor
from ml.anomaly_model import IsolationForestDetector, DEFAULT_MODEL_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PEAK_THRESHOLD_KW = 600.0
ZSCORE_THRESHOLD = 2.5
ZSCORE_WINDOW = 100  # must match edge_ai.py default


# ---------------------------------------------------------------------------
# Data helpers (same as train_model.py, repeated here to keep script standalone)
# ---------------------------------------------------------------------------

def _normal_reading(t: float) -> float:
    day_period = 24 * 3600
    base = 300.0 + 100.0 * np.sin(2 * np.pi * (t % day_period) / day_period)
    noise = np.random.normal(0.0, 10.0)
    return max(base + noise, 0.0)


def _peak_reading(t: float) -> float:
    return _normal_reading(t) + np.random.uniform(300.0, 500.0)


def _build_features(readings: np.ndarray) -> np.ndarray:
    extractor = FeatureExtractor()
    return np.array([extractor.update(float(r)) for r in readings], dtype=np.float64)


def _zscore_preds(readings: np.ndarray, window: int, threshold: float) -> np.ndarray:
    """Apply rolling robust Z-score (Median+MAD) to a 1-D readings array.

    Median and MAD are statistically robust to outliers (peaks), so the
    baseline doesn't drift even when 30% of the window contains spikes.
    """
    from collections import deque
    buf: deque = deque(maxlen=window)
    preds = np.zeros(len(readings), dtype=int)
    for i, r in enumerate(readings):
        buf.append(r)
        if len(buf) < 10:
            continue
        arr = np.array(buf)
        median = float(np.median(arr))
        mad = float(np.median(np.abs(arr - median)))
        robust_std = 1.4826 * mad if mad > 0.0 else float(arr.std(ddof=0))
        if robust_std == 0:
            continue
        z = (r - median) / robust_std
        if z > threshold:
            preds[i] = 1
    return preds


# ---------------------------------------------------------------------------
# Evaluation helper
# ---------------------------------------------------------------------------

def _evaluate_scenario(
    detector: IsolationForestDetector,
    n_samples: int,
    peak_rate: float,
    scenario_name: str,
    t_offset: float = 0.0,
) -> dict:
    """Run one evaluation scenario; return metrics dict."""
    t_values = np.linspace(t_offset, t_offset + n_samples * 2, n_samples)
    labels = (np.random.random(n_samples) < peak_rate).astype(int)
    readings = np.array([
        _peak_reading(t) if labels[i] else _normal_reading(t)
        for i, t in enumerate(t_values)
    ])

    X = _build_features(readings)
    thr_preds = (readings > PEAK_THRESHOLD_KW).astype(int)
    zsc_preds = _zscore_preds(readings, ZSCORE_WINDOW, ZSCORE_THRESHOLD)

    if_anom, _ = detector.predict_batch(X)
    if_preds = if_anom.astype(int)

    # Ensemble policies
    ensemble_or  = np.maximum(if_preds, np.maximum(thr_preds, zsc_preds))
    ensemble_maj = ((if_preds + thr_preds + zsc_preds) >= 2).astype(int)  # 2-of-3 vote

    scenario_results = {}
    for name, preds in [
        ("Isolation Forest",          if_preds),
        ("Fixed Threshold 600kW",     thr_preds),
        ("Rolling Z-Score (z>2.5)",   zsc_preds),
        ("Ensemble OR  (any trigger)", ensemble_or),
        ("Ensemble MAJ (2-of-3 vote)", ensemble_maj),
    ]:
        y = labels
        tp = int(((preds == 1) & (y == 1)).sum())
        fp = int(((preds == 1) & (y == 0)).sum())
        tn = int(((preds == 0) & (y == 0)).sum())
        fn = int(((preds == 0) & (y == 1)).sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        acc  = (tp + tn) / len(y)
        scenario_results[name] = {
            "TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "Precision": round(prec, 4),
            "Recall":    round(rec, 4),
            "F1":        round(f1, 4),
            "Accuracy":  round(acc, 4),
        }

    return scenario_results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    np.random.seed(0)

    print("\n" + "=" * 72)
    print("  Peak Load Detection - Model Evaluation")
    print("  CO326 Edge AI + Industrial IoT, Group 25")
    print("=" * 72 + "\n")

    # Load model
    try:
        detector = IsolationForestDetector.load(DEFAULT_MODEL_PATH)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    scenarios = [
        ("Balanced (10% peaks)",       2000,  0.10, 100_000.0),
        ("Rare events (2% peaks)",     2000,  0.02, 200_000.0),
        ("High load (30% peaks)",      2000,  0.30, 300_000.0),
    ]

    all_results = {}
    for name, n, rate, offset in scenarios:
        logger.info("Running scenario: %s ...", name)
        results = _evaluate_scenario(detector, n, rate, name, offset)
        all_results[name] = results

        print(f"\n{'-' * 72}")
        print(f"  Scenario: {name}  |  n={n}, peak_rate={rate*100:.0f}%")
        print(f"{'-' * 72}")
        header = f"  {'Detector':<35} {'Prec':>7} {'Rec':>7} {'F1':>7} {'Acc':>7}  Confusion"
        print(header)
        print(f"  {'-'*35} {'-'*7} {'-'*7} {'-'*7} {'-'*7}  {'-'*22}")
        for det_name, m in results.items():
            cm = f"TP={m['TP']:4d} FP={m['FP']:4d} FN={m['FN']:4d}"
            print(
                f"  {det_name:<35} {m['Precision']:>7.4f} {m['Recall']:>7.4f}"
                f" {m['F1']:>7.4f} {m['Accuracy']:>7.4f}  {cm}"
            )

    print("\n" + "=" * 72)

    # Save report
    report_path = _HERE / "ml" / "evaluation_report.json"
    report = {
        "model_path": str(DEFAULT_MODEL_PATH),
        "scenarios": all_results,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[OK] Full report saved to: {report_path}")


if __name__ == "__main__":
    main()
