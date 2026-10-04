"""Host observability: structured events, central redaction, console/file sinks."""

from observability.emitter import NULL_EMITTER, Emitter, Scope, StageTimer
from observability.events import (
    RESERVED_EVENT_TYPES,
    Event,
    EventType,
    Severity,
    new_trace_id,
)
from observability.factory import build_emitter

__all__ = [
    "Emitter",
    "Event",
    "EventType",
    "NULL_EMITTER",
    "RESERVED_EVENT_TYPES",
    "Scope",
    "Severity",
    "StageTimer",
    "build_emitter",
    "new_trace_id",
]
