"""Runtime adapter for a persisted WP-104 affect classifier."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any

import numpy as np

from ml.affect.artifacts import load_model_artifact, read_artifact_metadata
from ml.affect.features import FeatureExtractionError, extract_features

ALLOWED_AFFECT_LEVELS = frozenset({"Low", "Moderate", "High"})
logger = logging.getLogger(__name__)


def _artifact_version(path: Path) -> str | None:
    """Version from the artifact's metadata sidecar; None if it is absent or unreadable.

    Observability must not break model loading, so a missing sidecar is not an error.
    """
    try:
        version = read_artifact_metadata(path).get("artifact_version")
    except Exception:  # noqa: BLE001
        return None
    return str(version) if version else None


class ClassifierAffectDetector:
    """Load one trained artifact and expose the existing detector contract."""

    def __init__(self, model_path: str | Path):
        """Initialize the ClassifierAffectDetector and establish its runtime state."""
        self.model_path = Path(model_path)
        self.model = load_model_artifact(self.model_path)
        self._model_version = _artifact_version(self.model_path)

    @property
    def model_name(self) -> str:
        """Artifact name, reported in OBS-LOG model events."""
        return self.model_path.stem

    @property
    def model_version(self) -> str | None:
        """``artifact_version`` from the artifact's metadata sidecar, if present."""
        return self._model_version

    def detect(self, audio: Any, sample_rate: int) -> str:
        """Detect the current affect level from the supplied audio."""
        if audio is None:
            raise ValueError("audio is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        start = time.perf_counter()
        try:
            result = extract_features(np.asarray(audio), sample_rate)
            inference_start = time.perf_counter()
            prediction = self.model.predict(result.vector.reshape(1, -1))
            inference_elapsed = time.perf_counter() - inference_start
        except FeatureExtractionError:
            raise
        except Exception as exc:
            raise RuntimeError("Affect classifier inference failed") from exc
        total_elapsed = time.perf_counter() - start
        level = str(prediction[0])
        if level not in ALLOWED_AFFECT_LEVELS:
            raise RuntimeError(f"Affect classifier returned invalid level: {level!r}")
        logger.info(
            "wp104_affect_detect feature_extraction_s=%.6f inference_s=%.6f total_s=%.6f",
            result.elapsed_seconds,
            inference_elapsed,
            total_elapsed,
        )
        return level
