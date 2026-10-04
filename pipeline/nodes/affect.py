"""WP-104 affect branch with a survivable detector fallback."""

from __future__ import annotations

import logging
from contextlib import nullcontext

from observability import NULL_EMITTER, Emitter, ModelCall
from observability.emitter import error_info
from pipeline.state import DialogueState

ALLOWED_AFFECT_LEVELS = frozenset({"Low", "Moderate", "High"})
logger = logging.getLogger(__name__)


class AffectDetectionError(RuntimeError):
    """Raised when the affect input contract is invalid."""


def make_affect_node(
    detector, *, fallback_level: str = "Low", emitter: Emitter = NULL_EMITTER
):
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

        trace_id = state.get("trace_id") or ""
        session_id = state.get("session_id")
        # OBS-LOG FR-O6: only a real model gets inference events. The
        # development fallback detector is deterministic (``is_model = False``).
        if getattr(detector, "is_model", True):
            inference = emitter.model_inference(
                trace_id=trace_id,
                component="affect",
                session_id=session_id,
                model_name=getattr(detector, "model_name", None),
            )
        else:
            inference = nullcontext(ModelCall())

        degradation_reason = None
        try:
            with inference as call:
                affect_level = detector.detect(audio, sample_rate=sample_rate)
                if affect_level not in ALLOWED_AFFECT_LEVELS:
                    raise AffectDetectionError(
                        f"Affect detector returned invalid level: {affect_level!r}"
                    )
                call.result["prediction"] = affect_level
        except Exception as exc:
            degradation_reason = "affect_detector_failure"
            # OBS-LOG FR-O11: emitted where the fallback is decided, in
            # addition to the stage's own lifecycle events.
            emitter.degradation(
                trace_id=trace_id,
                component="affect",
                session_id=session_id,
                reason_code=degradation_reason,
                metadata={"fallback_level": fallback_level},
                error=error_info(
                    exc,
                    component="affect",
                    operation="detect",
                    recoverable=True,
                ),
            )
            logger.warning(
                "WP-104 affect detection degraded to %s after detector failure: %s",
                fallback_level,
                exc,
            )
            affect_level = fallback_level
        return {
            "affect_level": affect_level,
            "degradation_reason": degradation_reason,
        }

    return affect_node
