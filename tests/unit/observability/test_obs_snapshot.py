from __future__ import annotations

from observability import Emitter, EventType, Severity


class ListSink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)

    def close(self) -> None:
        return None


def _debug(include_text: bool = False):
    sink = ListSink()
    return Emitter([sink], level=Severity.DEBUG, include_text=include_text), sink


def test_snapshot_logs_selected_variables_with_callsite() -> None:
    emitter, sink = _debug()
    emitter.snapshot("after policy", trace_id="t1", component="policy", score=0.82, retries=2, ok=True)
    rec = sink.records[0]
    assert rec["event_type"] == "state_snapshot" and rec["severity"] == "DEBUG"
    assert rec["metadata"]["label"] == "after policy"
    assert rec["metadata"]["variables"] == {"score": 0.82, "retries": 2, "ok": True}
    assert "test_obs_snapshot.py" in rec["metadata"]["callsite"]
    assert "test_snapshot_logs_selected_variables_with_callsite" in rec["metadata"]["callsite"]


def test_snapshot_is_a_noop_above_debug() -> None:
    sink = ListSink()
    emitter = Emitter([sink], level=Severity.INFO)
    assert emitter.snapshot("x", trace_id="t", component="c", a=1) == ""
    assert sink.records == []


def test_strings_are_hash_only_by_type_even_under_unlisted_names() -> None:
    emitter, sink = _debug()
    emitter.snapshot("stt", trace_id="t", component="stt", msg="remind me at noon", rule="R2", plain=["rule"])
    v = sink.records[0]["metadata"]["variables"]
    assert "msg" not in v and v["msg_length"] == 17 and len(v["msg_hash"]) == 16
    assert v["rule"] == "R2"  # explicitly vouched for


def test_nested_strings_are_masked_and_secrets_still_redacted() -> None:
    emitter, sink = _debug()
    emitter.snapshot(
        "ctx", trace_id="t", component="c",
        context={"notes": "private", "ids": ["a", "b"], "password": "p"},
    )
    ctx = sink.records[0]["metadata"]["variables"]["context"]
    assert "notes" not in ctx and ctx["notes_length"] == 7
    assert ctx["ids"][0] == {"length": 1, "hash": ctx["ids"][0]["hash"]}
    assert ctx["password"] == "[REDACTED]"


def test_credentials_get_no_length_or_hash() -> None:
    emitter, sink = _debug()
    emitter.snapshot("auth", trace_id="t", component="c", token="abc123", api_key="k")
    v = sink.records[0]["metadata"]["variables"]
    assert v == {"token": "[REDACTED]", "api_key": "[REDACTED]"}


def test_full_text_shown_only_with_include_text() -> None:
    emitter, sink = _debug(include_text=True)
    emitter.snapshot("stt", trace_id="t", component="stt", msg="remind me at noon")
    assert sink.records[0]["metadata"]["variables"]["msg"] == "remind me at noon"


def test_diff_reports_only_changed_listed_keys() -> None:
    emitter, sink = _debug()
    before = {"intent": "add_task", "affect_level": "Low", "draft": "hello", "audio": [1, 2]}
    after = {"intent": "add_task", "affect_level": "High", "proposed": 1, "draft": "hello!"}
    emitter.diff(
        "node4_policy", trace_id="t", component="policy", before=before, after=after,
        keys=["intent", "affect_level", "proposed", "draft", "absent"], plain=["affect_level"],
    )
    m = sink.records[0]["metadata"]
    assert m["watched"] == ["intent", "affect_level", "proposed", "draft", "absent"]
    assert set(m["changes"]) == {"affect_level", "proposed", "draft"}
    assert m["changes"]["affect_level"] == {"before": "Low", "after": "High"}
    assert m["changes"]["proposed"] == {"after": 1}  # added key has no 'before'
    assert "after" not in m["changes"]["draft"] and "after_hash" in m["changes"]["draft"]


def test_bound_scope_keeps_trace_session_and_callsite() -> None:
    emitter, sink = _debug()
    log = emitter.bind(trace_id="t9", component="llm", session_id="s1")
    log.snapshot("draft", n_tokens=40)
    log.diff("state", before={"a": 1}, after={"a": 2}, keys=["a"])
    first, second = sink.records
    assert first["trace_id"] == second["trace_id"] == "t9" and first["session_id"] == "s1"
    assert second["metadata"]["changes"] == {"a": {"before": 1, "after": 2}}
    assert "test_bound_scope_keeps_trace_session_and_callsite" in first["metadata"]["callsite"]


def test_snapshot_never_raises_on_hostile_values() -> None:
    emitter, sink = _debug()

    class Bad:
        def __eq__(self, other):
            raise RuntimeError("no")

        def __str__(self):
            raise RuntimeError("no str")

    emitter.snapshot("x", trace_id="t", component="c", bad=Bad())
    emitter.diff("y", trace_id="t", component="c", before={"k": Bad()}, after={"k": Bad()}, keys=["k"])
    assert emitter.failures >= 0  # reaching here without an exception is the point
