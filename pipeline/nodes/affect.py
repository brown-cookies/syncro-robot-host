"""WP-104 affect branch with a survivable detector fallback."""

from __future__ import annotations

import logging

from pipeline.state import DialogueState

ALLOWED_AFFECT_LEVELS = frozenset({"Low", "Moderate", "High"})
logger = logging.getLogger(__name__)


class AffectDetectionError(RuntimeError):
    """Raised when the affect input contract is invalid."""


def make_affect_node(detector, *, fallback_level: str = "Low"):
    """Create the parallel affect graph node with a degraded-mode fallback."""
    if fallback_level not in ALLOWED_AFFECT_LEVELS:
        raise ValueError(f"Invalid affect fallback level: {fallback_level!r}")

    def affect_node(state: DialogueState) -> DialogueState:
        """Detect affect and downgrade to a safe level when detector execution fails."""
        audio = state.get("audio")
        sample_rate = state.get("sample_rate")
        if audio is None or sample_rate is None:
            raise AffectDetectionError(
                "Affect detection requires audio and sample_rate in DialogueState."
            )

        try:
            affect_level = detector.detect(audio, sample_rate=sample_rate)
            if affect_level not in ALLOWED_AFFECT_LEVELS:
                raise AffectDetectionError(
                    f"Affect detector returned invalid level: {affect_level!r}"
                )
        except Exception as exc:
            logger.warning(
                "WP-104 affect detection degraded to %s after detector failure: %s",
                fallback_level,
                exc,
            )
            affect_level = fallback_level
        return {"affect_level": affect_level}

    return affect_node
