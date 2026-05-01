#!/usr/bin/env python3
"""
train_model.py — Offline training pipeline for Peak Load Detection.

Workflow
--------
1. Generate a large synthetic dataset of *normal* industrial load readings
   using the same simulator logic as production, but WITHOUT injected peaks.
2. Run the FeatureExtractor over the time-series to build feature vectors.
3. Train an IsolationForest on those normal feature vectors.
4. Evaluate detection performance on a *labelled* test set (normal + peaks).
5. Save the fitted model to ml/isolation_forest.pkl.

Run from the python/ directory:
    python train_model.py

Optional arguments (environment variables):
    N_TRAIN_SAMPLES   Number of normal training samples (default: 5000)
    N_TEST_SAMPLES    Number of test samples, ~10% peaks (default: 1000)
    MODEL_PATH        Override save path
"""

import os
import sys
import time
import logging
import json
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))          # make ml/ importable when run directly

from ml.feature_engineering import FeatureExtractor, N_FEATURES, FEATURE_NAMES
from ml.anomaly_model import IsolationForestDetector, DEFAULT_MODEL_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
N_TRAIN_SAMPLES = int(os.environ.get("N_TRAIN_SAMPLES", 20000))
N_TEST_SAMPLES = int(os.environ.get("N_TEST_SAMPLES", 2000))
MODEL_PATH = os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH)

PEAK_THRESHOLD_KW = 600.0   # must match edge_ai.py


# ---------------------------------------------------------------------------
# Data generation (pure normal, no peaks)
# ---------------------------------------------------------------------------

def generate_normal_reading(t_seconds: float) -> float:
    """
    Simulate a *normal* industrial load reading (no spike injection).
    Mirrors simulator.py logic but omits the random spike.
    """
    day_period = 24 * 3600
    base = 300.0 + 100.0 * np.sin(2 * np.pi * (t_seconds % day_period) / day_period)
    noise = np.random.normal(0.0, 10.0)
    return max(base + noise, 0.0)


def generate_peak_reading(t_seconds: float) -> float:
    """Simulate a load reading that contains a deliberate peak spike."""
    base = generate_normal_reading(t_seconds)
    spike = np.random.uniform(300.0, 500.0)
    return base + spike


def build_feature_matrix(readings: np.ndarray) -> np.ndarray:
    """
    Convert a 1-D array of power readings into a feature matrix.

    Args:
        readings: Shape (n,) of power_kw values in time order.

    Returns:
        X: Shape (n, N_FEATURES) feature matrix.
    """
    extractor = FeatureExtractor()
    rows = []
    for r in readings:
        fv = extractor.update(float(r))
        rows.append(fv)
    return np.array(rows, dtype=np.float64)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(n_train: int = N_TRAIN_SAMPLES) -> IsolationForestDetector:
    """
    Generate normal training data, extract features, fit IsolationForest.
    """
    logger.info("Generating %d normal training readings (multi-day cycle) ...", n_train)
    t0 = time.time()
    # Span multiple full 24-hour cycles so the IF learns the full sinusoidal envelope
    # 2-second sensor interval: 24h = 43,200 readings; n_train covers many cycles
    t_values = np.linspace(0, n_train * 2, n_train)
    readings = np.array([generate_normal_reading(t) for t in t_values])

    logger.info("Extracting features …")
    X_train = build_feature_matrix(readings)

    # Drop the first 10 rows where rolling stats have NaN (insufficient history)
    X_train = X_train[10:]
    logger.info("Training feature matrix shape: %s", X_train.shape)

    detector = IsolationForestDetector(
        n_estimators=150,
        contamination=0.01,   # match true anomaly rate; 0.08 caused over-flagging
        max_samples=256,
        random_state=42,
    )
    detector.fit(X_train)
    elapsed = time.time() - t0
    logger.info("Training complete in %.1f s", elapsed)
    return detector


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _compute_zscore_preds(
    readings: np.ndarray, window: int = 100, threshold: float = 2.5
) -> np.ndarray:
    """Apply rolling robust Z-score (Median+MAD) detection to a 1-D readings array."""
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


def evaluate(detector: IsolationForestDetector, n_test: int = N_TEST_SAMPLES):
    """
    Evaluate the detector on a labelled test set.
    Reports precision, recall, F1, and accuracy.
    """
    logger.info("Generating %d labelled test readings (10%% peaks) ...", n_test)

    # Build a mixed time-series: 90% normal, 10% peaks (randomly injected)
    t_values = np.linspace(86400, 86400 + n_test * 2, n_test)  # offset by 1 day
    labels = (np.random.random(n_test) < 0.10).astype(int)  # 1 = peak

    readings = np.array([
        generate_peak_reading(t) if labels[i] else generate_normal_reading(t)
        for i, t in enumerate(t_values)
    ])

    X_test = build_feature_matrix(readings)
    y_true = labels

    threshold_preds = (readings > PEAK_THRESHOLD_KW).astype(int)
    zscore_preds = _compute_zscore_preds(readings)
    is_anomaly_arr, _ = detector.predict_batch(X_test)
    if_preds = is_anomaly_arr.astype(int)

    # Ensemble policies
    # OR: flag if any detector triggers (max recall, may have more FP)
    ensemble_or = np.maximum(if_preds, np.maximum(threshold_preds, zscore_preds))
    # Majority (>=2 of 3): better balance of precision and recall
    ensemble_maj = ((if_preds + threshold_preds + zscore_preds) >= 2).astype(int)

    results = {}
    for name, preds in [
        ("Isolation Forest", if_preds),
        ("Fixed Threshold (600 kW)", threshold_preds),
        ("Rolling Z-Score (z>2.5)", zscore_preds),
        ("Ensemble OR  (any trigger)", ensemble_or),
        ("Ensemble MAJ (2-of-3 vote)", ensemble_maj),
    ]:
        tp = int(((preds == 1) & (y_true == 1)).sum())
        fp = int(((preds == 1) & (y_true == 0)).sum())
        tn = int(((preds == 0) & (y_true == 0)).sum())
        fn = int(((preds == 0) & (y_true == 1)).sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        accuracy = (tp + tn) / len(y_true)
        results[name] = {
            "TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "Precision": round(precision, 4),
            "Recall": round(recall, 4),
            "F1": round(f1, 4),
            "Accuracy": round(accuracy, 4),
        }

    # Print nicely
    print("\n" + "=" * 70)
    print("  EVALUATION RESULTS")
    print("=" * 70)
    for detector_name, metrics in results.items():
        print(f"\n  [{detector_name}]")
        print(f"    TP={metrics['TP']:4d}  FP={metrics['FP']:4d}  "
              f"TN={metrics['TN']:4d}  FN={metrics['FN']:4d}")
        print(f"    Precision: {metrics['Precision']:.4f}  "
              f"Recall: {metrics['Recall']:.4f}  "
              f"F1: {metrics['F1']:.4f}  "
              f"Accuracy: {metrics['Accuracy']:.4f}")
    print("=" * 70)

    # Save evaluation report
    report_path = _HERE / "ml" / "evaluation_report.json"
    report = {
        "n_test_samples": n_test,
        "peak_injection_rate": 0.10,
        "peak_threshold_kw": PEAK_THRESHOLD_KW,
        "detectors": results,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Evaluation report saved to %s", report_path)

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 70)
    print("  Peak Load Detection --- ML Training Pipeline")
    print("  CO326 Edge AI + Industrial IoT")
    print("=" * 70 + "\n")

    # Train
    detector = train(N_TRAIN_SAMPLES)

    # Evaluate
    evaluate(detector, N_TEST_SAMPLES)

    # Save model
    saved_path = detector.save(MODEL_PATH)
    logger.info("Model saved to: %s", saved_path)

    print(f"\n[OK] Model ready at: {saved_path}")
    print("  Start the system with: python mqtt_publisher.py\n")


if __name__ == "__main__":
    main()
