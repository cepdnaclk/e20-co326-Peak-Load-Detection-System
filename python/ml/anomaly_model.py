"""
Isolation Forest anomaly detector for Peak Load Detection.

Wraps scikit-learn's IsolationForest with:
  - Model persistence (save / load)
  - Feature-vector based inference
  - Anomaly score exposure (for confidence reporting)
  - Online warm-up mode that accumulates readings before predicting

The model is trained offline via ``train_model.py`` and loaded at
edge runtime. This keeps inference latency to microseconds.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Default path for saved model file (next to this package)
_HERE = Path(__file__).parent
DEFAULT_MODEL_PATH = str(_HERE / "isolation_forest.pkl")


class IsolationForestDetector:
    """
    Lightweight wrapper around sklearn IsolationForest + StandardScaler.

    Features are standardized (zero-mean, unit-variance) before being
    passed to the forest, which ensures all features contribute equally
    to anomaly scoring regardless of their original scale.

    Usage (inference):
        detector = IsolationForestDetector.load()
        is_anomaly, score = detector.predict(feature_vector)

    Usage (training):
        detector = IsolationForestDetector()
        detector.fit(X_train)
        detector.save()
    """

    def __init__(
        self,
        n_estimators: int = 150,
        contamination: float = 0.01,   # set to actual expected anomaly fraction
        max_samples: int = 256,
        random_state: int = 42,
    ) -> None:
        """
        Args:
            n_estimators:   Number of isolation trees.
            contamination:  Expected fraction of anomalies in training data.
                            Set slightly above the true rate so the decision
                            boundary is not too tight.
            max_samples:    Samples per tree (fixed 256 for reproducibility).
            random_state:   Seed for reproducibility.
        """
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import StandardScaler

        self._scaler = StandardScaler()
        self._model = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            max_samples=max_samples,
            random_state=random_state,
        )
        self._fitted = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, X: np.ndarray) -> "IsolationForestDetector":
        """
        Train the model on *normal* power load feature vectors.

        Args:
            X: Array of shape (n_samples, n_features). Should contain
               only *normal* readings so the model learns the expected
               distribution and flags deviations as anomalies.

        Returns:
            self (for chaining)
        """
        logger.info("Fitting IsolationForest on %d samples ...", len(X))
        # Replace any NaN with column means (safety for early readings)
        col_means = np.nanmean(X, axis=0)
        nan_mask = np.isnan(X)
        for col in range(X.shape[1]):
            X[nan_mask[:, col], col] = col_means[col]
        # Standardize features so scale differences don't bias tree splits
        X_scaled = self._scaler.fit_transform(X)
        self._model.fit(X_scaled)
        self._fitted = True
        logger.info("IsolationForest training complete.")
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, feature_vector: np.ndarray) -> Tuple[bool, float]:
        """
        Classify one feature vector.

        Args:
            feature_vector: 1-D array of shape (n_features,).

        Returns:
            (is_anomaly, score)
            - is_anomaly: True when the model classifies this as anomalous.
            - score: Anomaly score in [-1, 0]. More negative → more anomalous.

        Raises:
            RuntimeError: If the model has not been fitted/loaded yet.
        """
        if not self._fitted:
            raise RuntimeError(
                "Model is not fitted. Call fit() or load() first."
            )

        x = feature_vector.reshape(1, -1).copy()
        # Replace NaN with 0 (safe fallback for cold-start readings)
        x[np.isnan(x)] = 0.0
        x_scaled = self._scaler.transform(x)

        pred = self._model.predict(x_scaled)[0]        # +1 normal, -1 anomaly
        score = self._model.score_samples(x_scaled)[0]  # log-likelihood proxy
        return (pred == -1), float(score)

    def predict_batch(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Classify a batch of feature vectors.

        Returns:
            (is_anomaly_array, scores_array) – shapes (n_samples,)
        """
        if not self._fitted:
            raise RuntimeError("Model not fitted. Call fit() or load() first.")
        X = X.copy()
        X[np.isnan(X)] = 0.0
        X_scaled = self._scaler.transform(X)
        preds = self._model.predict(X_scaled)
        scores = self._model.score_samples(X_scaled)
        return (preds == -1), scores

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Optional[str] = None) -> str:
        """
        Persist the fitted model to disk using joblib.

        Args:
            path: File path (default: DEFAULT_MODEL_PATH next to this module).

        Returns:
            Absolute path of the saved file.
        """
        import joblib

        if not self._fitted:
            raise RuntimeError("Cannot save an unfitted model.")
        path = path or DEFAULT_MODEL_PATH
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # Save the entire instance (model + scaler) so they stay in sync
        joblib.dump(self, path)
        logger.info("Model saved to %s", path)
        return str(path)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "IsolationForestDetector":
        """
        Load a previously saved model.

        Args:
            path: File path (default: DEFAULT_MODEL_PATH).

        Returns:
            Fitted IsolationForestDetector instance.

        Raises:
            FileNotFoundError: If the model file does not exist.
        """
        import joblib

        path = path or DEFAULT_MODEL_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Model file not found: {path}\n"
                "Run `python train_model.py` first to train and save the model."
            )
        instance = joblib.load(path)
        if not isinstance(instance, cls):
            raise RuntimeError(
                f"Loaded object is {type(instance)}, expected {cls}. "
                "The model file may be from an older version. Re-run train_model.py."
            )
        logger.info("Loaded IsolationForest model from %s", path)
        return instance

    @property
    def is_fitted(self) -> bool:
        return self._fitted
