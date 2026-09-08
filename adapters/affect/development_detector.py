"""Deterministic development fallback for the affect detector."""

from __future__ import annotations

from typing import Any


class DevelopmentAffectDetector:
    """Provide a deterministic Low affect level when the ML artifact is unavailable."""

    def detect(self, audio: Any, sample_rate: int) -> str:
        """Return the safe development fallback affect level for the supplied audio."""
        if audio is None:
            raise ValueError("audio is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        return "Low"
