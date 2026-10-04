from __future__ import annotations

import json
import threading

import pytest

from observability import Emitter, EventType, Severity
from observability.sinks import ConsoleSink, FileSink


class ListSink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)

    def close(self) -> None:
        return None


class BrokenSink:
    def write(self, record: dict) -> None:
        raise OSError("disk full")

    def close(self) -> None:
        raise OSError("close failed")


def _emit(emitter: Emitter, **kw):
    return emitter.event(trace_id="t1", component="policy", event_type=EventType.BRANCH_SELECTED, **kw)


def test_level_is_respected() -> None:
    sink = ListSink()
    emitter = Emitter([sink], level=Severity.WARNING)
    _emit(emitter, severity=Severity.INFO)
    _emit(emitter, severity=Severity.WARNING)
    assert [r["severity"] for r in sink.records] == ["WARNING"]


def test_reserved_action_events_are_never_emitted() -> None:
    sink = ListSink()
    emitter = Emitter([sink], level=Severity.DEBUG)
    for etype in (EventType.ACTION_STARTED, EventType.ACTION_COMPLETED, EventType.ACTION_FAILED):
        emitter.event(trace_id="t", component="c", event_type=etype)
    emitter.event(trace_id="t", component="c", event_type=EventType.ACTION_SELECTED)
    assert [r["event_type"] for r in sink.records] == ["action_selected"]


def test_broken_sink_never_raises_and_does_not_block_other_sinks() -> None:
    good = ListSink()
    emitter = Emitter([BrokenSink(), good])
    _emit(emitter)  # must not raise
    emitter.close()  # must not raise
    assert len(good.records) == 1
    assert emitter.failures >= 1


def test_redaction_runs_before_the_sink() -> None:
    sink = ListSink()
    emitter = Emitter([sink])
    _emit(emitter, metadata={"transcript": "secret words", "password": "p"})
    meta = sink.records[0]["metadata"]
    assert "transcript" not in meta and meta["transcript_length"] == 12
    assert meta["password"] == "[REDACTED]"


def test_full_text_needs_include_text_and_a_debug_event() -> None:
    sink = ListSink()
    emitter = Emitter([sink], level=Severity.DEBUG, include_text=True)
    _emit(emitter, severity=Severity.DEBUG, metadata={"transcript": "hello"})
    _emit(emitter, severity=Severity.INFO, metadata={"transcript": "hello"})
    assert sink.records[0]["metadata"]["transcript"] == "hello"
    assert "transcript" not in sink.records[1]["metadata"]


def test_stage_success_emits_started_and_completed_with_one_duration() -> None:
    sink = ListSink()
    emitter = Emitter([sink])
    with emitter.stage(trace_id="t1", component="llm", session_id="s1") as timer:
        timer.output["proposed_action"] = "respond"
    started, completed = sink.records
    assert (started["event_type"], completed["event_type"]) == ("stage_started", "stage_completed")
    assert started["trace_id"] == completed["trace_id"] == "t1"
    assert completed["parent_event_id"] == started["event_id"]
    assert completed["duration_ms"] == pytest.approx(timer.elapsed_s * 1000.0)
    assert completed["metadata"]["proposed_action"] == "respond"


def test_stage_failure_emits_failed_and_reraises_the_original() -> None:
    sink = ListSink()
    emitter = Emitter([sink])
    boom = ValueError("bad slot")
    with pytest.raises(ValueError) as caught:
        with emitter.stage(trace_id="t1", component="intent"):
            raise boom
    assert caught.value is boom
    failed = sink.records[-1]
    assert failed["event_type"] == "stage_failed" and failed["severity"] == "ERROR"
    assert failed["duration_ms"] is not None
    assert failed["error"]["error_type"] == "ValueError"
    assert failed["error"]["operation"] == "intent"
    assert "ValueError" in failed["error"]["traceback"]


def test_stage_still_times_and_raises_when_sinks_are_broken() -> None:
    emitter = Emitter([BrokenSink()])
    with emitter.stage(trace_id="t", component="c") as timer:
        pass
    assert timer.elapsed_s >= 0.0


def test_console_and_file_sinks_share_one_schema(tmp_path, capsys) -> None:
    path = tmp_path / "logs" / "events.jsonl"
    file_sink = FileSink(str(path))
    emitter = Emitter([ConsoleSink(), file_sink])
    _emit(emitter, metadata={"rule": "R2"})
    emitter.close()
    console_line = capsys.readouterr().err.strip()
    file_line = path.read_text(encoding="utf-8").strip()
    assert json.loads(console_line).keys() == json.loads(file_line).keys()
    assert console_line == file_line


def test_file_sink_is_safe_under_concurrent_writers(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    emitter = Emitter([FileSink(str(path))])

    def worker(n: int) -> None:
        for i in range(50):
            _emit(emitter, metadata={"worker": n, "i": i})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    emitter.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200
    assert all(json.loads(line)["trace_id"] == "t1" for line in lines)

def test_stage_skip_replaces_completed_and_keeps_duration_and_parent() -> None:
    sink = ListSink()
    emitter = Emitter([sink], level=Severity.DEBUG)
    with emitter.stage(trace_id="t1", component="llm") as timer:
        timer.output["marker"] = 1
        timer.skip("clarification_only")
    types = [r["event_type"] for r in sink.records]
    assert types == ["stage_started", "stage_skipped"]
    started, skipped = sink.records
    assert skipped["status"] == "skipped"
    assert skipped["parent_event_id"] == started["event_id"]
    assert skipped["duration_ms"] == timer.elapsed_s * 1000.0
    assert skipped["metadata"] == {"reason": "clarification_only", "marker": 1}


def test_stage_without_skip_still_completes_and_failure_wins_over_skip() -> None:
    sink = ListSink()
    emitter = Emitter([sink], level=Severity.DEBUG)
    with emitter.stage(trace_id="t1", component="a"):
        pass
    with pytest.raises(ValueError):
        with emitter.stage(trace_id="t2", component="b") as timer:
            timer.skip("will be overridden by the raise")
            raise ValueError("boom")
    assert [r["event_type"] for r in sink.records] == [
        "stage_started", "stage_completed", "stage_started", "stage_failed",
    ]
