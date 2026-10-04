"""Structured event contract for host observability (OBS-LOG spec, Section 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Severity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        """Numeric ordering so the emitter can filter by LOG_LEVEL."""
        return _RANK[self.value]


_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class EventType(str, Enum):
    """Closed vocabulary. New types need spec review, not ad-hoc strings."""

    INTERACTION_STARTED = "interaction_started"
    INTERACTION_COMPLETED = "interaction_completed"
    INTERACTION_FAILED = "interaction_failed"

    INPUT_RECEIVED = "input_received"
    INPUT_REJECTED = "input_rejected"

    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    STAGE_SKIPPED = "stage_skipped"

    MODEL_INFERENCE_STARTED = "model_inference_started"
    MODEL_INFERENCE_COMPLETED = "model_inference_completed"
    MODEL_INFERENCE_FAILED = "model_inference_failed"

    DECISION_EVALUATED = "decision_evaluated"
    BRANCH_SELECTED = "branch_selected"

    ACTION_SELECTED = "action_selected"
    ACTION_STARTED = "action_started"  # reserved (FR-O8)
    ACTION_COMPLETED = "action_completed"  # reserved (FR-O8)
    ACTION_FAILED = "action_failed"  # reserved (FR-O8)

    DEGRADATION_APPLIED = "degradation_applied"  # FR-O11


# FR-O8: no action executor exists yet, so these must never be emitted.
RESERVED_EVENT_TYPES = frozenset(
    {
        EventType.ACTION_STARTED,
        EventType.ACTION_COMPLETED,
        EventType.ACTION_FAILED,
    }
)


def new_trace_id() -> str:
    """Mint the one-per-interaction trace id (FR-O1)."""
    return str(uuid4())


@dataclass(frozen=True, slots=True)
class Event:
    trace_id: str
    component: str
    event_type: EventType
    severity: Severity = Severity.INFO
    status: str = "success"
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    duration_ms: float | None = None
    parent_event_id: str | None = None
    error: dict[str, Any] | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """
        Canonical record. Every key is always present (null when absent)
        so console and file sinks share one schema.
        """
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "parent_event_id": self.parent_event_id,
            "timestamp": self.timestamp,
            "component": self.component,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
            "error": dict(self.error) if self.error is not None else None,
        }
