from __future__ import annotations

from observability import RESERVED_EVENT_TYPES, Event, EventType, Severity, new_trace_id


def test_event_record_has_every_schema_key() -> None:
    record = Event(trace_id="t", component="policy", event_type=EventType.BRANCH_SELECTED).to_dict()
    assert set(record) == {
        "event_id", "trace_id", "session_id", "parent_event_id", "timestamp",
        "component", "event_type", "severity", "status", "duration_ms",
        "metadata", "error",
    }
    assert record["event_type"] == "branch_selected"
    assert record["severity"] == "INFO"
    assert record["session_id"] is None and record["error"] is None


def test_event_ids_are_unique_and_trace_ids_are_distinct() -> None:
    a = Event(trace_id="t", component="c", event_type=EventType.STAGE_STARTED)
    b = Event(trace_id="t", component="c", event_type=EventType.STAGE_STARTED)
    assert a.event_id != b.event_id
    assert new_trace_id() != new_trace_id()


def test_severity_ordering() -> None:
    assert Severity.DEBUG.rank < Severity.INFO.rank < Severity.WARNING.rank
    assert Severity.WARNING.rank < Severity.ERROR.rank < Severity.CRITICAL.rank


def test_action_execution_events_are_reserved() -> None:
    assert RESERVED_EVENT_TYPES == {
        EventType.ACTION_STARTED, EventType.ACTION_COMPLETED, EventType.ACTION_FAILED,
    }
    assert EventType.ACTION_SELECTED not in RESERVED_EVENT_TYPES
