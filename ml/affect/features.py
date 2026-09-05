"""openSMILE eGeMAPSv02 feature extraction for WP-104."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import numpy as np

TARGET_SAMPLE_RATE = 16_000
EXPECTED_FEATURE_COUNT = 88


class FeatureExtractionError(RuntimeError):
    """Raised when audio cannot be converted into an eGeMAPSv02 vector."""


@dataclass(frozen=True, slots=True)
class FeatureExtractionResult:
    vector: np.ndarray
    elapsed_seconds: float


def _require_opensmile() -> Any:
    """Validate that the openSMILE dependency is available before feature extraction."""
    try:
        import opensmile
    except ImportError as exc:
        raise FeatureExtractionError(
            "openSMILE is required for WP-104 feature extraction; install requirements.txt"
        ) from exc
    return opensmile


def _to_mono_float32(audio: np.ndarray) -> np.ndarray:
    """Normalize PCM input into mono float32 samples for feature extraction."""
    array = np.asarray(audio)
    if array.ndim == 1:
        mono = array
    elif array.ndim == 2:
        # Accept either (samples, channels) or (channels, samples); the host contract is mono,
        # so multi-channel development inputs are mixed down deterministically.
        axis = 1 if array.shape[1] <= 8 else 0
        mono = array.mean(axis=axis)
    else:
        raise ValueError(f"audio must be 1-D or 2-D, got shape {array.shape}")
    mono = np.asarray(mono, dtype=np.float32)
    if mono.size == 0:
        raise ValueError("audio must not be empty")
    return mono


def resample_to_target(audio: np.ndarray, sample_rate: int, target_rate: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    """Resample mono PCM audio to the fixed feature-extraction sample rate."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    mono = _to_mono_float32(audio)
    if sample_rate == target_rate:
        return mono
    output_length = max(1, round(mono.size * target_rate / sample_rate))
    source_x = np.linspace(0.0, 1.0, num=mono.size, endpoint=False, dtype=np.float64)
    target_x = np.linspace(0.0, 1.0, num=output_length, endpoint=False, dtype=np.float64)
    return np.interp(target_x, source_x, mono).astype(np.float32)


def create_smile():
    """Create the configured openSMILE eGeMAPSv02 feature extractor."""
    opensmile = _require_opensmile()
    return opensmile.Smile(
        feature_set=opensmile.FeatureSet.eGeMAPSv02,
        feature_level=opensmile.FeatureLevel.Functionals,
    )


def extract_features(
    audio: np.ndarray,
    sample_rate: int,
    *,
    smile=None,
) -> FeatureExtractionResult:
    """Extract one deterministic eGeMAPSv02 feature vector from audio."""
    if audio is None:
        raise ValueError("audio is required")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    prepared = resample_to_target(audio, sample_rate)
    extractor = smile or create_smile()
    start = time.perf_counter()
    try:
        frame = extractor.process_signal(prepared, TARGET_SAMPLE_RATE)
    except Exception as exc:
        raise FeatureExtractionError("openSMILE could not analyze the supplied audio") from exc
    elapsed = time.perf_counter() - start
    vector = frame.to_numpy(dtype=np.float64, copy=True).reshape(-1)
    if vector.size != EXPECTED_FEATURE_COUNT:
        raise FeatureExtractionError(
            f"Expected {EXPECTED_FEATURE_COUNT} eGeMAPSv02 functionals, got {vector.size}"
        )
    if not np.isfinite(vector).all():
        raise FeatureExtractionError("eGeMAPSv02 feature vector contains non-finite values")
    return FeatureExtractionResult(vector=vector, elapsed_seconds=elapsed)
