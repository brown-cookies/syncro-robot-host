"""WP-103 affect branch boundary; WP-104 supplies the real detector."""

from __future__ import annotations

from pipeline.state import DialogueState

ALLOWED_AFFECT_LEVELS = frozenset({"Low", "Moderate", "High"})


class AffectDetectionError(RuntimeError):
    """Raised when the affect adapter cannot produce a valid level."""


def make_affect_node(detector):
    """Create the parallel affect graph node with its injected detector."""

    def affect_node(state: DialogueState) -> DialogueState:
        """Detect affect from the same raw audio and store the validated level in dialogue state."""
        audio = state.get("audio")
        sample_rate = state.get("sample_rate")
        if audio is None or sample_rate is None:
            raise AffectDetectionError(
                "Affect detection requires audio and sample_rate in DialogueState."
            )

        affect_level = detector.detect(audio, sample_rate=sample_rate)
        if affect_level not in ALLOWED_AFFECT_LEVELS:
            raise AffectDetectionError(
                f"Affect detector returned invalid level: {affect_level!r}"
            )
        return {"affect_level": affect_level}

    return affect_node
