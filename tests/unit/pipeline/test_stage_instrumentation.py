"""OBS-LOG Step 2: stage lifecycle, timing, state-at-boundaries, errors.

Covers FR-O4 (lifecycle, stage_skipped, re-raise unchanged), FR-O5 (selected
fields only; DEBUG-only diffs), FR-O9 (failure shape) and FR-O10 (event
duration_ms is the same reading as stage_timings_s; interaction events carry
latency). Verification items 2, 3, 6, 18, 19 (partly 16).
"""

from __future__ import annotations

import json
from uuid import uuid4

import numpy as np
import pytest

pytest.importorskip("langgraph")

from adapters.stt.whisper_adapter import STTAdapterError
from audio.resample import to_pcm16_16k
from observability import Emitter, EventType, Severity
from pipeline.graph import build_dialogue_graph
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext
from storage.sqlite_store import SQLiteStore

STAGES = ("stt", "affect", "intent", "context", "llm", "policy", "output")
UTTERANCE = "zebra-marker utterance about my dentist"
DRAFT = "Here is a zebra-marker draft reply."


class ListSink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)

    def close(self) -> None:
        return None


class FakeSTT:
    def transcribe(self, audio, sample_rate):
        return UTTERANCE


class FakeIntent:
    def __init__(self, result=("ask_status", 0.91, {})) -> None:
        self.result = result

    def classify(self, transcript):
        return self.result


class FakeAffect:
    def detect(self, audio, sample_rate):
        return "Low"


class FakeLLM:
    def generate(self, prompt):
        return json.dumps({"response_text": DRAFT, "proposed_action": "respond"})


class FakeTTS:
    def synthesize(self, text):
        return np.zeros(160, dtype=np.float32), 16_000


def make_emitter(level: Severity = Severity.INFO, include_text: bool = False):
    sink = ListSink()
    return Emitter([sink], level=level, include_text=include_text), sink


class SpyStore(SQLiteStore):
    """Counts context lookups so a 'skipped' stage can be shown to have done no work."""

    retrievals = 0

    def retrieve_context(self, *args, **kwargs):
        type(self).retrievals += 1
        return super().retrieve_context(*args, **kwargs)


class CountingLLM(FakeLLM):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return super().generate(prompt)


def build(tmp_path, emitter, *, stt=None, intent=None, llm=None, affect=None, store=None):
    store = store or SQLiteStore(str(tmp_path / "obs.db"))
    store.ensure_user("u1")
    graph = build_dialogue_graph(
        stt=stt or FakeSTT(),
        intent_classifier=intent or FakeIntent(),
        llm=llm or FakeLLM(),
        store=store,
        affect_detector=affect or FakeAffect(),
        confidence_threshold=0.60,
        context_top_k=5,
        deadline_proximity_hours=2,
        grace_window_minutes=15,
        default_lead_time=15,
        emitter=emitter,
    )
    return graph, store


def initial_state(trace_id: str | None = None) -> dict:
    state = {
        "session_id": "s1",
        "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32),
        "sample_rate": 16_000,
    }
    if trace_id is not None:
        state["trace_id"] = trace_id
    return state


def of_type(records, event_type: EventType, component: str | None = None):
    return [
        r for r in records
        if r["event_type"] == event_type.value
        and (component is None or r["component"] == component)
    ]


# --- FR-O4: lifecycle -------------------------------------------------------


def test_every_stage_emits_started_and_completed_under_one_trace_id(tmp_path):
    emitter, sink = make_emitter()
    graph, _ = build(tmp_path, emitter)
    trace_id = str(uuid4())

    graph.invoke(initial_state(trace_id))

    for stage in STAGES:
        started = of_type(sink.records, EventType.STAGE_STARTED, stage)
        completed = of_type(sink.records, EventType.STAGE_COMPLETED, stage)
        assert len(started) == 1, stage
        assert len(completed) == 1, stage
        assert completed[0]["parent_event_id"] == started[0]["event_id"]
        assert completed[0]["duration_ms"] is not None
        assert {started[0]["trace_id"], completed[0]["trace_id"]} == {trace_id}
        assert started[0]["session_id"] == "s1"
    assert not of_type(sink.records, EventType.STAGE_FAILED)


def test_a_failing_stage_emits_stage_failed_and_reraises_the_original(tmp_path):
    class BrokenSTT:
        def transcribe(self, audio, sample_rate):
            raise STTAdapterError("decoder exploded")

    emitter, sink = make_emitter()
    graph, _ = build(tmp_path, emitter, stt=BrokenSTT())

    with pytest.raises(STTAdapterError, match="decoder exploded"):
        graph.invoke(initial_state(str(uuid4())))

    failed = of_type(sink.records, EventType.STAGE_FAILED, "stt")
    assert len(failed) == 1
    event = failed[0]
    assert event["severity"] == "ERROR" and event["status"] == "failure"
    assert event["duration_ms"] is not None
    assert event["error"]["error_type"] == "STTAdapterError"
    assert event["error"]["component"] == "stt"
    assert "decoder exploded" in event["error"]["message"]
    assert not of_type(sink.records, EventType.STAGE_COMPLETED, "stt")


def test_skipped_stage_ends_with_stage_skipped_and_no_stage_completed(tmp_path):
    """stage_skipped is the terminal event: started -> skipped, never started ->
    skipped -> completed. It still carries the stage's duration and parent."""
    emitter, sink = make_emitter()
    graph, _ = build(tmp_path, emitter, intent=FakeIntent(("ask_status", 0.30, {})))

    result = graph.invoke(initial_state(str(uuid4())))

    for stage in ("context", "llm"):
        started = of_type(sink.records, EventType.STAGE_STARTED, stage)
        skipped = of_type(sink.records, EventType.STAGE_SKIPPED, stage)
        assert len(started) == 1 and len(skipped) == 1, stage
        assert not of_type(sink.records, EventType.STAGE_COMPLETED, stage), stage
        assert skipped[0]["status"] == "skipped"
        assert skipped[0]["metadata"]["reason"] == "clarification_only"
        assert skipped[0]["parent_event_id"] == started[0]["event_id"]
        # FR-O10 / verification 18 hold for skipped stages too.
        assert skipped[0]["duration_ms"] == result["stage_timings_s"][stage] * 1000.0
    intent_done = of_type(sink.records, EventType.STAGE_COMPLETED, "intent")[0]
    assert intent_done["metadata"]["clarify"] is True


def test_every_stage_ends_in_exactly_one_terminal_event(tmp_path):
    terminal = {
        EventType.STAGE_COMPLETED.value,
        EventType.STAGE_SKIPPED.value,
        EventType.STAGE_FAILED.value,
    }
    for confidence in (0.91, 0.30):  # normal path, clarification path
        emitter, sink = make_emitter()
        graph, _ = build(tmp_path, emitter, intent=FakeIntent(("ask_status", confidence, {})))
        graph.invoke(initial_state(str(uuid4())))
        for stage in STAGES:
            ends = [
                r for r in sink.records
                if r["component"] == stage and r["event_type"] in terminal
            ]
            assert len(ends) == 1, (confidence, stage, [e["event_type"] for e in ends])


def test_skipped_means_the_stage_really_did_no_work(tmp_path):
    """Guards the skip predicate in pipeline/stage_obs.py against drifting away from
    the bypass condition inside the context and llm nodes."""
    SpyStore.retrievals = 0
    llm = CountingLLM()
    emitter, sink = make_emitter()
    graph, _ = build(
        tmp_path, emitter, llm=llm, store=SpyStore(str(tmp_path / "spy.db")),
        intent=FakeIntent(("ask_status", 0.30, {})),
    )
    graph.invoke(initial_state(str(uuid4())))
    assert llm.calls == 0 and SpyStore.retrievals == 0
    assert len(of_type(sink.records, EventType.STAGE_SKIPPED)) == 2

    # And the normal path does the work and is never marked skipped.
    llm2 = CountingLLM()
    emitter2, sink2 = make_emitter()
    graph2, _ = build(
        tmp_path, emitter2, llm=llm2, store=SpyStore(str(tmp_path / "spy2.db")),
    )
    graph2.invoke(initial_state(str(uuid4())))
    assert llm2.calls == 1 and SpyStore.retrievals == 1
    assert not of_type(sink2.records, EventType.STAGE_SKIPPED)


def test_no_stage_is_marked_skipped_on_the_normal_path(tmp_path):
    emitter, sink = make_emitter()
    graph, _ = build(tmp_path, emitter)
    graph.invoke(initial_state(str(uuid4())))
    assert not of_type(sink.records, EventType.STAGE_SKIPPED)


def test_graph_without_a_trace_id_is_invalid_and_fails_before_any_work(tmp_path):
    """FR-O1: no trace_id means no legitimate interaction. There is no legacy
    timing mode; the first stage refuses, before any adapter or model runs."""
    class CountingSTT(FakeSTT):
        calls = 0

        def transcribe(self, audio, sample_rate):
            type(self).calls += 1
            return super().transcribe(audio, sample_rate)

    llm = CountingLLM()
    emitter, sink = make_emitter()
    graph, _ = build(tmp_path, emitter, stt=CountingSTT(), llm=llm)

    with pytest.raises(RuntimeError, match="requires trace_id"):
        graph.invoke(initial_state())  # no trace_id

    assert CountingSTT.calls == 0 and llm.calls == 0
    assert sink.records == []


def test_graph_runs_and_times_with_the_default_null_emitter(tmp_path):
    """Strict trace_id does not make observability mandatory: with the no-op
    emitter the one timing path still feeds stage_timings_s."""
    store = SQLiteStore(str(tmp_path / "null.db"))
    store.ensure_user("u1")
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=FakeIntent(), llm=FakeLLM(), store=store,
        affect_detector=FakeAffect(), confidence_threshold=0.60, context_top_k=5,
        deadline_proximity_hours=2, grace_window_minutes=15, default_lead_time=15,
    )
    result = graph.invoke(initial_state(str(uuid4())))
    assert set(STAGES) <= set(result["stage_timings_s"])


# --- FR-O10: timing is one reading ------------------------------------------


def test_event_duration_equals_stage_timings_for_every_stage(tmp_path):
    emitter, sink = make_emitter()
    graph, _ = build(tmp_path, emitter)

    result = graph.invoke(initial_state(str(uuid4())))

    timings = result["stage_timings_s"]
    for stage in STAGES:
        completed = of_type(sink.records, EventType.STAGE_COMPLETED, stage)[0]
        assert completed["duration_ms"] == timings[stage] * 1000.0, stage


# --- FR-O5: only selected fields, no raw text/audio -------------------------


def test_stage_events_record_selected_fields(tmp_path):
    emitter, sink = make_emitter()
    graph, _ = build(tmp_path, emitter)
    graph.invoke(initial_state(str(uuid4())))

    stt_started = of_type(sink.records, EventType.STAGE_STARTED, "stt")[0]
    assert stt_started["metadata"] == {"audio_samples": 160, "sample_rate": 16_000}
    affect_done = of_type(sink.records, EventType.STAGE_COMPLETED, "affect")[0]
    assert affect_done["metadata"] == {"affect_level": "Low", "degradation_reason": None}
    intent_done = of_type(sink.records, EventType.STAGE_COMPLETED, "intent")[0]
    assert intent_done["metadata"]["intent"] == "ask_status"
    assert intent_done["metadata"]["intent_confidence"] == 0.91
    policy_done = of_type(sink.records, EventType.STAGE_COMPLETED, "policy")[0]
    assert policy_done["metadata"]["policy_rule"] == "n/a"
    assert policy_done["metadata"]["action_taken"] == "deliver"
    output_done = of_type(sink.records, EventType.STAGE_COMPLETED, "output")[0]
    assert output_done["metadata"]["state_tag"] == "speaking"


def test_text_is_hash_only_by_default_and_slot_values_never_appear(tmp_path):
    emitter, sink = make_emitter()
    intent = FakeIntent(("add_task", 0.95, {"title": "SLOT-SECRET-VALUE"}))
    graph, _ = build(tmp_path, emitter, intent=intent)

    graph.invoke(initial_state(str(uuid4())))

    blob = json.dumps(sink.records)
    assert "zebra-marker" not in blob
    assert "SLOT-SECRET-VALUE" not in blob
    stt_done = of_type(sink.records, EventType.STAGE_COMPLETED, "stt")[0]
    assert stt_done["metadata"]["transcript_length"] == len(UTTERANCE)
    assert len(stt_done["metadata"]["transcript_hash"]) == 16
    intent_done = of_type(sink.records, EventType.STAGE_COMPLETED, "intent")[0]
    assert intent_done["metadata"]["slot_keys"] == ["title"]
    assert "[AUDIO OMITTED]" not in blob and "BYTES OMITTED" not in blob


# --- FR-O5 variable tracing: DEBUG only, named keys only ---------------------


def test_no_state_snapshots_above_debug(tmp_path):
    emitter, sink = make_emitter(Severity.INFO)
    graph, _ = build(tmp_path, emitter)
    graph.invoke(initial_state(str(uuid4())))
    assert not of_type(sink.records, EventType.STATE_SNAPSHOT)


def test_debug_diffs_cover_only_llm_and_policy_named_keys_and_hash_strings(tmp_path):
    emitter, sink = make_emitter(Severity.DEBUG)  # include_text stays False
    graph, _ = build(tmp_path, emitter)
    graph.invoke(initial_state(str(uuid4())))

    snaps = of_type(sink.records, EventType.STATE_SNAPSHOT)
    assert {s["component"] for s in snaps} == {"llm", "policy"}
    assert all(s["severity"] == "DEBUG" and s["metadata"]["callsite"] for s in snaps)
    llm_snap = next(s for s in snaps if s["component"] == "llm")
    assert llm_snap["metadata"]["watched"] == ["draft", "proposed_action"]
    assert set(llm_snap["metadata"]["changes"]) <= {"draft", "proposed_action"}
    assert "zebra-marker" not in json.dumps(snaps)
    draft_change = llm_snap["metadata"]["changes"]["draft"]
    assert draft_change["after_length"] == len(DRAFT)
    assert len(draft_change["after_hash"]) == 16


def test_full_text_reaches_a_diff_only_with_debug_and_include_text(tmp_path):
    emitter, sink = make_emitter(Severity.DEBUG, include_text=True)
    graph, _ = build(tmp_path, emitter)
    graph.invoke(initial_state(str(uuid4())))

    llm_snap = next(
        s for s in of_type(sink.records, EventType.STATE_SNAPSHOT) if s["component"] == "llm"
    )
    assert llm_snap["metadata"]["changes"]["draft"]["after"] == DRAFT


# --- FR-O9 / FR-O10 at the interaction boundary ------------------------------


def make_runner(graph, store, emitter) -> InteractionRunner:
    return InteractionRunner(
        graph=graph, store=store, tts=FakeTTS(), resampler=to_pcm16_16k, emitter=emitter
    )


def session() -> SessionContext:
    return SessionContext(session_id="s1", user_id="u1", started_monotonic=0.0)


def test_interaction_events_carry_latency_and_match_the_decision_trace(tmp_path):
    emitter, sink = make_emitter()
    graph, store = build(tmp_path, emitter)

    result = make_runner(graph, store, emitter).run(
        session=session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000
    )

    started = of_type(sink.records, EventType.INTERACTION_STARTED)
    completed = of_type(sink.records, EventType.INTERACTION_COMPLETED)
    assert len(started) == 1 and len(completed) == 1
    assert completed[0]["metadata"]["latency_ms"] == result.latency_ms
    assert completed[0]["metadata"]["latency_basis"] == result.latency_basis
    # One trace_id across the runner's events, every stage event, and the result.
    assert {r["trace_id"] for r in sink.records} == {result.trace_id}
    # Stage events sit between interaction_started and interaction_completed.
    order = [r["event_type"] for r in sink.records]
    assert order[0] == "interaction_started" and order[-1] == "interaction_completed"


def test_failure_attaches_structured_error_from_the_failure_map(tmp_path):
    class BrokenSTT:
        def transcribe(self, audio, sample_rate):
            raise STTAdapterError("decoder exploded")

    emitter, sink = make_emitter()
    graph, store = build(tmp_path, emitter, stt=BrokenSTT())

    with pytest.raises(InteractionError) as raised:
        make_runner(graph, store, emitter).run(
            session=session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000
        )

    failed = of_type(sink.records, EventType.INTERACTION_FAILED)
    assert len(failed) == 1
    error = failed[0]["error"]
    assert error["error_type"] == "STTAdapterError"
    assert error["error_code"] == "malformed_audio"  # _FAILURE_MAP wire code
    assert error["component"] == "stt"  # where it failed, not "runner"
    assert error["operation"] == "run"
    assert error["recoverable"] is False
    assert error["retry_count"] is None  # unknown stays unknown
    assert "decoder exploded" in error["message"]
    assert "Traceback" in error["traceback"]  # kept in the log record only
    # The failing stage and the interaction share one trace_id.
    stage_failed = of_type(sink.records, EventType.STAGE_FAILED, "stt")[0]
    assert stage_failed["trace_id"] == failed[0]["trace_id"] == raised.value.trace_id
    # The original exception is untouched for the transport's own handling.
    assert isinstance(raised.value.cause, STTAdapterError)
    assert raised.value.wire_code == "malformed_audio"
