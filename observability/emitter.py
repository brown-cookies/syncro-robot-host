"""The Observability API components call (OBS-LOG spec, Sections 2, 4, 9).

Contract: observability never decides or alters functional behavior, and
``emit`` never raises. A broken sink or a bad event is counted in
``failures`` and dropped; the host operation's result stays authoritative.
"""

from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from observability.events import RESERVED_EVENT_TYPES, Event, EventType, Severity
from observability.redaction import redact
from observability.sinks import Sink


@dataclass(slots=True)
class StageTimer:
    """Handed to the body of ``Emitter.stage``.

    ``elapsed_s`` is set once, from one monotonic reading, when the block
    exits. Use it for ``stage_timings_s`` so the existing timing field and the
    event's ``duration_ms`` can never disagree (FR-O10).
    ``output`` is attached to the ``stage_completed`` event (FR-O5).
    """

    elapsed_s: float = 0.0
    started_event_id: str = ""
    output: dict[str, Any] = field(default_factory=dict)


def error_info(exc: BaseException, *, component: str, operation: str) -> dict[str, Any]:
    """FR-O9 error shape. The traceback stays in the diagnostic log only."""
    return {
        "error_type": type(exc).__name__,
        "error_code": getattr(exc, "wire_code", None),
        "component": component,
        "operation": operation,
        "message": str(exc)[:500],
        "recoverable": None,
        "retry_count": None,
        "traceback": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )[-4000:],
    }


class Emitter:
    def __init__(
        self,
        sinks: Sequence[Sink],
        *,
        level: Severity = Severity.INFO,
        include_text: bool = False,
    ) -> None:
        self._sinks = list(sinks)
        self._level = level
        self._include_text = include_text
        self.failures = 0  # events dropped because redaction or a sink failed

    @property
    def level(self) -> Severity:
        return self._level

    def emit(self, event: Event) -> None:
        try:
            if event.event_type in RESERVED_EVENT_TYPES:
                return
            if event.severity.rank < self._level.rank:
                return
            full_text = self._include_text and event.severity is Severity.DEBUG
            record = redact(event.to_dict(), include_text=full_text)
        except Exception:  # noqa: BLE001 - observability must never raise
            self.failures += 1
            return
        for sink in self._sinks:
            try:
                sink.write(record)
            except Exception:  # noqa: BLE001 - one bad sink must not stop the rest
                self.failures += 1

    def event(
        self,
        *,
        trace_id: str,
        component: str,
        event_type: EventType,
        severity: Severity = Severity.INFO,
        status: str = "success",
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        duration_ms: float | None = None,
        parent_event_id: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> str:
        """Build and emit one event. Returns its event_id ('' if it could not be built)."""
        try:
            event = Event(
                trace_id=trace_id,
                component=component,
                event_type=event_type,
                severity=severity,
                status=status,
                metadata=dict(metadata or {}),
                session_id=session_id,
                duration_ms=duration_ms,
                parent_event_id=parent_event_id,
                error=error,
            )
        except Exception:  # noqa: BLE001
            self.failures += 1
            return ""
        self.emit(event)
        return event.event_id

    @contextmanager
    def stage(
        self,
        *,
        trace_id: str,
        component: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[StageTimer]:
        """FR-O4 lifecycle: stage_started, then stage_completed or stage_failed.

        The original exception is re-raised untouched.
        """
        timer = StageTimer()
        timer.started_event_id = self.event(
            trace_id=trace_id,
            component=component,
            event_type=EventType.STAGE_STARTED,
            status="started",
            metadata=metadata,
            session_id=session_id,
        )
        start = time.monotonic()
        try:
            yield timer
        except BaseException as exc:
            timer.elapsed_s = time.monotonic() - start
            self.event(
                trace_id=trace_id,
                component=component,
                event_type=EventType.STAGE_FAILED,
                severity=Severity.ERROR,
                status="failure",
                session_id=session_id,
                duration_ms=timer.elapsed_s * 1000.0,
                parent_event_id=timer.started_event_id or None,
                error=error_info(exc, component=component, operation=component),
            )
            raise
        else:
            timer.elapsed_s = time.monotonic() - start
            self.event(
                trace_id=trace_id,
                component=component,
                event_type=EventType.STAGE_COMPLETED,
                session_id=session_id,
                duration_ms=timer.elapsed_s * 1000.0,
                parent_event_id=timer.started_event_id or None,
                metadata=timer.output,
            )

    def close(self) -> None:
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:  # noqa: BLE001
                self.failures += 1


# Safe default for components built without observability (tests, scripts).
NULL_EMITTER = Emitter(sinks=())
