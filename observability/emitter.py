"""The Observability API components call (OBS-LOG spec, Sections 2, 4, 9).

Contract: observability never decides or alters functional behavior, and
``emit`` never raises. A broken sink or a bad event is counted in
``failures`` and dropped; the host operation's result stays authoritative.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Sequence

from observability.events import RESERVED_EVENT_TYPES, Event, EventType, Severity
from observability.redaction import mask_text, redact
from observability.sinks import Sink


@dataclass(slots=True)
class StageTimer:
    """Handed to the body of ``Emitter.stage``.

    ``elapsed_s`` is set once, from one monotonic reading, when the block
    exits. Use it for ``stage_timings_s`` so the existing timing field and the
    event's ``duration_ms`` can never disagree (FR-O10).
    ``output`` is attached to the terminal event (FR-O5).
    ``skip(reason)`` ends the stage as ``stage_skipped`` instead of
    ``stage_completed``: the stage's normal work was bypassed (FR-O4).
    """

    elapsed_s: float = 0.0
    started_event_id: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    skip_reason: str | None = None

    def skip(self, reason: str) -> None:
        self.skip_reason = reason


_MISSING = object()


def _callsite(depth: int) -> str:
    """'file.py:123 function' of the code that called the public API (debugger-style)."""
    try:
        frame = sys._getframe(depth)
        return f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_lineno} {frame.f_code.co_name}"
    except Exception:  # noqa: BLE001
        return ""


def error_info(
    exc: BaseException,
    *,
    component: str,
    operation: str,
    error_code: str | None = None,
    recoverable: bool | None = None,
    retry_count: int | None = None,
) -> dict[str, Any]:
    """FR-O9 error shape. The traceback stays in the diagnostic log only.

    ``error_code`` defaults to the exception's own ``wire_code`` when it has
    one; callers that have classified the failure (the runner's _FAILURE_MAP
    disposition) pass the stable code explicitly. ``recoverable`` and
    ``retry_count`` stay None ("unknown") unless the caller actually knows.
    """
    return {
        "error_type": type(exc).__name__,
        "error_code": error_code if error_code is not None else getattr(exc, "wire_code", None),
        "component": component,
        "operation": operation,
        "message": str(exc)[:500],
        "recoverable": recoverable,
        "retry_count": retry_count,
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
        """FR-O4 lifecycle: stage_started, then exactly one terminal event:
        stage_completed, stage_skipped (the body called ``timer.skip``) or
        stage_failed. Every terminal event carries ``duration_ms``.

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
                error=error_info(exc, component=component,
                                 operation=component),
            )
            raise
        else:
            timer.elapsed_s = time.monotonic() - start
            skipped = timer.skip_reason is not None
            self.event(
                trace_id=trace_id,
                component=component,
                event_type=(
                    EventType.STAGE_SKIPPED if skipped else EventType.STAGE_COMPLETED
                ),
                status="skipped" if skipped else "success",
                session_id=session_id,
                duration_ms=timer.elapsed_s * 1000.0,
                parent_event_id=timer.started_event_id or None,
                metadata=(
                    {"reason": timer.skip_reason, **timer.output}
                    if skipped
                    else timer.output
                ),
            )

    def bind(self, *, trace_id: str, component: str, session_id: str | None = None) -> "Scope":
        """Fix trace/component once so call sites stay one-liners."""
        return Scope(self, trace_id, component, session_id)

    def snapshot(
        self,
        label: str,
        /,
        *,
        trace_id: str,
        component: str,
        session_id: str | None = None,
        plain: Iterable[str] = (),
        **variables: Any,
    ) -> str:
        """Watch: log the named variables at this point. DEBUG only.

        Only what you pass is logged (never whole state). Strings are hash-only
        unless named in ``plain`` or full text is enabled (LOG_INCLUDE_TEXT=true
        with LOG_LEVEL=DEBUG). Don't name a variable ``label``, ``trace_id``,
        ``component``, ``session_id`` or ``plain``.
        """
        return self._snapshot(
            label, trace_id=trace_id, component=component, session_id=session_id,
            plain=plain, variables=variables, site=_callsite(2),
        )

    def diff(
        self,
        label: str,
        /,
        *,
        trace_id: str,
        component: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        keys: Iterable[str],
        session_id: str | None = None,
        plain: Iterable[str] = (),
    ) -> str:
        """State transition: log before/after for the listed keys that changed. DEBUG only."""
        return self._diff(
            label, trace_id=trace_id, component=component, session_id=session_id,
            before=before, after=after, keys=keys, plain=plain, site=_callsite(
                2),
        )

    def _snapshot(self, label, *, trace_id, component, session_id, plain, variables, site) -> str:
        if Severity.DEBUG.rank < self._level.rank:
            return ""  # cheap no-op unless LOG_LEVEL=DEBUG
        try:
            shown = variables if self._include_text else mask_text(
                variables, plain=frozenset(plain))
            return self.event(
                trace_id=trace_id, component=component, session_id=session_id,
                event_type=EventType.STATE_SNAPSHOT, severity=Severity.DEBUG,
                metadata={"label": label,
                          "callsite": site, "variables": shown},
            )
        except Exception:  # noqa: BLE001
            self.failures += 1
            return ""

    def _diff(self, label, *, trace_id, component, session_id, before, after, keys, plain, site) -> str:
        if Severity.DEBUG.rank < self._level.rank:
            return ""
        try:
            plain_set = frozenset(plain)
            watched = list(keys)
            changes: dict[str, Any] = {}
            for key in watched:
                old = before.get(key, _MISSING)
                new = after.get(key, _MISSING)
                try:
                    same = bool(old == new)
                except Exception:  # noqa: BLE001 - e.g. array comparison; treat as changed
                    same = False
                if same:
                    continue
                pair: dict[str, Any] = {}
                if old is not _MISSING:
                    pair["before"] = old
                if new is not _MISSING:
                    pair["after"] = new
                changes[key] = pair if (
                    self._include_text or key in plain_set) else mask_text(pair)
            return self.event(
                trace_id=trace_id, component=component, session_id=session_id,
                event_type=EventType.STATE_SNAPSHOT, severity=Severity.DEBUG,
                metadata={"label": label, "callsite": site,
                          "watched": watched, "changes": changes},
            )
        except Exception:  # noqa: BLE001
            self.failures += 1
            return ""

    def close(self) -> None:
        for sink in self._sinks:
            try:
                sink.close()
            except Exception:  # noqa: BLE001
                self.failures += 1


class Scope:
    """An Emitter bound to one trace/component: ``log = obs.bind(...)``, then
    ``log.snapshot("after policy", rule=rule, score=score)``."""

    __slots__ = ("_emitter", "_trace_id", "_component", "_session_id")

    def __init__(self, emitter: Emitter, trace_id: str, component: str, session_id: str | None) -> None:
        self._emitter = emitter
        self._trace_id = trace_id
        self._component = component
        self._session_id = session_id

    def snapshot(self, label: str, /, *, plain: Iterable[str] = (), **variables: Any) -> str:
        return self._emitter._snapshot(
            label, trace_id=self._trace_id, component=self._component,
            session_id=self._session_id, plain=plain, variables=variables, site=_callsite(
                2),
        )

    def diff(
        self,
        label: str,
        /,
        *,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        keys: Iterable[str],
        plain: Iterable[str] = (),
    ) -> str:
        return self._emitter._diff(
            label, trace_id=self._trace_id, component=self._component,
            session_id=self._session_id, before=before, after=after, keys=keys,
            plain=plain, site=_callsite(2),
        )


# Safe default for components built without observability (tests, scripts).
NULL_EMITTER = Emitter(sinks=())
