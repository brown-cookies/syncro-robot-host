"""OBS-LOG Step 3: domain events (FR-O6 model, FR-O7 decision, FR-O8 action,
FR-O11 degradation).

Verification items touched: 4 (model results and branches observable),
5 (selected vs executed), 7/16 (no text on guard events), 15 (affect fallback),
17 (reserved action events never emitted).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import get_args
from uuid import UUID, uuid4

import numpy as np
import pytest

pytest.importorskip("langgraph")

from audio.resample import to_pcm16_16k
from observability import Emitter, EventType, Severity
from pipeline.contracts import DegradationReason
from pipeline.graph import build_dialogue_graph
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext
from pipeline.nodes.llm import make_llm_node
from pipeline.nodes.policy import make_policy_node
from storage.sqlite_store import SQLiteStore

RESERVED = {"action_started", "action_completed", "action_failed"}
SECRET = "zebra-secret-words about my dentist"


class ListSink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)

    def close(self) -> None:
        return None


def make_emitter(level: Severity = Severity.DEBUG, include_text: bool = False):
    sink = ListSink()
    return Emitter([sink], level=level, include_text=include_text), sink


def of_type(records, event_type: str, component: str | None = None):
    return [
        r for r in records
        if r["event_type"] == event_type
        and (component is None or r["component"] == component)
    ]


class FakeSTT:
    model_name = "tiny.en"

    def transcribe(self, audio, sample_rate):
        return SECRET


class FakeIntent:
    model_name = "qwen-test"

    def classify(self, transcript):
        return ("ask_status", 0.91, {"free": SECRET})


class FakeAffect:
    model_name = "affect-svc"

    def detect(self, audio, sample_rate):
        return "Low"


class FakeLLM:
    model_name = "qwen-test"

    def __init__(self, response_text="All good.", proposed_action="respond"):
        self._payload = json.dumps(
            {"response_text": response_text, "proposed_action": proposed_action}
        )

    def generate(self, prompt):
        return self._payload


def build(tmp_path, emitter, **overrides):
    store = SQLiteStore(str(tmp_path / "obs.db"))
    store.ensure_user("u1")
    graph = build_dialogue_graph(
        stt=overrides.get("stt", FakeSTT()),
        intent_classifier=overrides.get("intent", FakeIntent()),
        llm=overrides.get("llm", FakeLLM()),
        store=store,
        affect_detector=overrides.get("affect", FakeAffect()),
        confidence_threshold=0.60,
        context_top_k=5,
        deadline_proximity_hours=2,
        grace_window_minutes=15,
        default_lead_time=15,
        emitter=emitter,
    )
    return graph


def initial_state(trace_id: str) -> dict:
    return {
        "trace_id": trace_id,
        "session_id": "s1",
        "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32),
        "sample_rate": 16_000,
    }


# --- FR-O6: model events ----------------------------------------------------


def test_model_events_for_stt_affect_intent_llm_share_the_trace_id(tmp_path):
    emitter, sink = make_emitter()
    graph = build(tmp_path, emitter)
    trace_id = str(uuid4())
    graph.invoke(initial_state(trace_id))

    for component in ("stt", "affect", "intent", "llm"):
        started = of_type(sink.records, "model_inference_started", component)
        completed = of_type(sink.records, "model_inference_completed", component)
        assert len(started) == 1 and len(completed) == 1, component
        assert completed[0]["trace_id"] == trace_id
        assert completed[0]["parent_event_id"] == started[0]["event_id"]
        assert completed[0]["duration_ms"] >= 0
        assert completed[0]["metadata"]["outcome"] == "success"
        assert completed[0]["metadata"]["model_name"]
    assert not of_type(sink.records, "model_inference_failed")


def test_model_events_carry_prediction_and_confidence_where_available(tmp_path):
    emitter, sink = make_emitter()
    build(tmp_path, emitter).invoke(initial_state(str(uuid4())))

    intent = of_type(sink.records, "model_inference_completed", "intent")[0]["metadata"]
    assert intent["prediction"] == "ask_status"
    assert intent["confidence"] == 0.91
    affect = of_type(sink.records, "model_inference_completed", "affect")[0]["metadata"]
    assert affect["prediction"] == "Low"
    assert "confidence" not in affect and "model_version" not in affect


def test_model_events_never_carry_raw_text_prompts_or_slots(tmp_path):
    emitter, sink = make_emitter(level=Severity.INFO)
    build(tmp_path, emitter).invoke(initial_state(str(uuid4())))

    blob = json.dumps(sink.records)
    assert "zebra-secret" not in blob and "dentist" not in blob
    stt = of_type(sink.records, "model_inference_completed", "stt")[0]["metadata"]
    assert stt["transcript_length"] == len(SECRET) and "transcript_hash" in stt
    assert "transcript" not in stt


def test_full_transcript_on_model_event_needs_debug_and_the_flag(tmp_path):
    emitter, sink = make_emitter(level=Severity.DEBUG, include_text=True)
    build(tmp_path, emitter).invoke(initial_state(str(uuid4())))

    # model_inference_completed is an INFO event: full text is DEBUG-only.
    stt = of_type(sink.records, "model_inference_completed", "stt")[0]["metadata"]
    assert "transcript" not in stt and "transcript_hash" in stt


def test_development_detector_is_not_a_model_so_no_affect_inference_events(tmp_path):
    from adapters.affect.development_detector import DevelopmentAffectDetector

    emitter, sink = make_emitter()
    build(tmp_path, emitter, affect=DevelopmentAffectDetector()).invoke(
        initial_state(str(uuid4()))
    )
    assert not of_type(sink.records, "model_inference_started", "affect")
    assert of_type(sink.records, "stage_completed", "affect")


def test_failed_llm_inference_is_recorded_and_the_error_propagates(tmp_path):
    class BadLLM(FakeLLM):
        def generate(self, prompt):
            return "not json at all"

    emitter, sink = make_emitter()
    with pytest.raises(ValueError):
        build(tmp_path, emitter, llm=BadLLM()).invoke(initial_state(str(uuid4())))

    failed = of_type(sink.records, "model_inference_failed", "llm")
    assert len(failed) == 1
    assert failed[0]["severity"] == "ERROR"
    assert failed[0]["error"]["error_type"] == "ValueError"
    assert failed[0]["duration_ms"] >= 0
    assert not of_type(sink.records, "model_inference_completed", "llm")
    assert of_type(sink.records, "stage_failed", "llm")  # lifecycle still intact


# --- FR-O7: mutation-claim guard branch ---------------------------------------


def llm_state(intent: str, **extra) -> dict:
    return {
        "trace_id": str(uuid4()), "session_id": "s1", "intent": intent,
        "intent_confidence": 0.9, "transcript": SECRET, "context": {}, **extra,
    }


def run_llm(intent: str, response_text: str, level=Severity.DEBUG, include_text=False):
    emitter, sink = make_emitter(level, include_text)
    node = make_llm_node(FakeLLM(response_text), emitter)
    state = llm_state(intent)
    result = node(state)
    return result, sink, state


def test_claim_rewrite_is_a_warning_branch_with_hashes_only():
    result, sink, state = run_llm("add_task", "I've added the task to your list.")

    (branch,) = of_type(sink.records, "branch_selected", "llm")
    assert branch["severity"] == "WARNING"
    assert branch["trace_id"] == state["trace_id"]
    md = branch["metadata"]
    assert md["rule"] == "mutation_claim_guard"
    assert md["reason_code"] == "claim_rewritten"
    assert md["draft_response_hash"] != md["final_response_hash"]
    assert md["final_response_length"] == len(result["draft_response"])
    assert "draft_response" not in md and "final_response" not in md
    assert "added" not in json.dumps(branch)


def test_warning_branch_stays_hashed_even_with_debug_and_text_flag():
    _, sink, _ = run_llm(
        "add_task", "I've added the task to your list.",
        level=Severity.DEBUG, include_text=True,
    )
    (branch,) = of_type(sink.records, "branch_selected", "llm")
    assert "draft_response" not in branch["metadata"]
    assert "draft_response_hash" in branch["metadata"]


def test_clean_proposal_is_passed_through_at_info():
    _, sink, _ = run_llm("add_task", "I can add that to your list if you like.")

    (branch,) = of_type(sink.records, "branch_selected", "llm")
    assert branch["severity"] == "INFO"
    md = branch["metadata"]
    assert md["reason_code"] == "passed_through"
    assert md["draft_response_hash"] == md["final_response_hash"]


def test_guard_branch_not_emitted_for_non_mutation_intents():
    _, sink, _ = run_llm("ask_status", "You have two tasks due today.")
    assert not of_type(sink.records, "branch_selected")


def test_guard_branch_not_emitted_on_the_clarify_path():
    emitter, sink = make_emitter()
    node = make_llm_node(FakeLLM(), emitter)
    node({**llm_state("add_task"), "proposed_action": "clarify",
          "final_response": "Could you say that again?"})
    assert not of_type(sink.records, "branch_selected")
    assert not of_type(sink.records, "model_inference_started")


# --- FR-O7 / FR-O8: policy decision and action selection ----------------------


def policy_state(intent: str, affect: str, proximity: str, **extra) -> dict:
    return {
        "trace_id": str(uuid4()), "session_id": "s1", "user_id": "u1",
        "intent": intent, "affect_level": affect, "deadline_proximity": proximity,
        "draft_response": "Sure.", "proposed_action": "snooze", **extra,
    }


def run_policy(state: dict, store=None):
    emitter, sink = make_emitter()
    node = make_policy_node(15, 15.0, store=store, emitter=emitter)
    return node(state), sink


def test_governed_intent_emits_decision_then_action_with_the_selected_rule():
    state = policy_state("snooze_reminder", "Moderate", "imminent")
    result, sink = run_policy(state)

    (decision,) = of_type(sink.records, "decision_evaluated", "policy")
    assert decision["metadata"] == {
        "intent": "snooze_reminder", "governed": True, "affect_level": "Moderate",
        "deadline_proximity": "imminent", "policy_rule": "R3",
    }
    (action,) = of_type(sink.records, "action_selected", "policy")
    assert action["metadata"] == {
        "proposed_action": "snooze", "action_taken": "soften", "policy_rule": "R3",
    }
    assert result["action_taken"] == "soften"
    order = [r["event_type"] for r in sink.records]
    assert order.index("decision_evaluated") < order.index("action_selected")
    assert {r["trace_id"] for r in sink.records} == {state["trace_id"]}


def test_non_policy_intent_records_rule_na_and_deliver():
    result, sink = run_policy(policy_state("ask_status", "High", "imminent"))

    decision = of_type(sink.records, "decision_evaluated")[0]["metadata"]
    assert decision["governed"] is False and decision["policy_rule"] == "n/a"
    action = of_type(sink.records, "action_selected")[0]["metadata"]
    assert action["action_taken"] == "deliver" and action["policy_rule"] == "n/a"
    assert result["policy_rule"] == "n/a"


def test_reserved_action_events_are_never_emitted(tmp_path):
    emitter, sink = make_emitter()
    build(tmp_path, emitter).invoke(initial_state(str(uuid4())))
    _, policy_sink = run_policy(policy_state("snooze_reminder", "High", "imminent"))

    for records in (sink.records, policy_sink.records):
        assert not RESERVED & {r["event_type"] for r in records}
    assert of_type(sink.records, "action_selected")


def test_emitter_drops_reserved_action_events_even_if_a_component_tries():
    emitter, sink = make_emitter()
    for event_type in (EventType.ACTION_STARTED, EventType.ACTION_COMPLETED,
                       EventType.ACTION_FAILED):
        emitter.event(trace_id=str(uuid4()), component="policy", event_type=event_type)
    assert sink.records == []


# --- FR-O11: degradation ------------------------------------------------------


def test_affect_detector_failure_degrades_with_warning_and_fallback(tmp_path):
    class BrokenAffect:
        model_name = "affect-svc"

        def detect(self, audio, sample_rate):
            raise RuntimeError("detector exploded")

    emitter, sink = make_emitter(level=Severity.INFO)
    trace_id = str(uuid4())
    state = build(tmp_path, emitter, affect=BrokenAffect()).invoke(initial_state(trace_id))

    assert state["affect_level"] == "Low"
    (degraded,) = of_type(sink.records, "degradation_applied", "affect")
    assert degraded["severity"] == "WARNING"
    assert degraded["trace_id"] == trace_id
    assert degraded["metadata"]["reason_code"] == "affect_detector_failure"
    assert degraded["metadata"]["fallback_level"] == "Low"
    assert degraded["error"]["error_type"] == "RuntimeError"
    # in addition to, not instead of, the stage's own lifecycle events
    assert of_type(sink.records, "stage_completed", "affect")
    assert of_type(sink.records, "model_inference_failed", "affect")


def test_no_degradation_event_when_everything_works(tmp_path):
    emitter, sink = make_emitter(level=Severity.INFO)
    build(tmp_path, emitter).invoke(initial_state(str(uuid4())))
    assert not of_type(sink.records, "degradation_applied")


# --- FR-O11: runner / transport degradations ----------------------------------


class _Store:
    def __init__(self):
        self.saved, self.saved_degraded = [], []

    def ensure_user(self, user_id):
        pass

    def save_decision_trace(self, record):
        self.saved.append(record)

    def save_degraded_trace(self, record):
        self.saved_degraded.append(record)


class _FailingGraph:
    def invoke(self, state):
        raise RuntimeError("boom")


class _NeverTTS:
    def synthesize(self, text):  # pragma: no cover - never reached
        raise AssertionError


def _runner(emitter, graph=None, store=None):
    return InteractionRunner(
        graph=graph or _FailingGraph(), store=store or _Store(), tts=_NeverTTS(),
        resampler=to_pcm16_16k, emitter=emitter,
    )


def _session():
    return SessionContext(session_id="s1", user_id="u1", started_monotonic=0.0)


@pytest.mark.parametrize("reason", ["session_timeout", "queue_overflow"])
def test_transport_degradation_reuses_the_supplied_trace_id(reason):
    emitter, sink = make_emitter(level=Severity.WARNING)
    store = _Store()
    trace_id = str(uuid4())
    _runner(emitter, store=store).persist_transport_degraded_trace(
        session=_session(), wire_code=reason, degradation_reason=reason,
        trace_id=trace_id,
    )

    (degraded,) = of_type(sink.records, "degradation_applied")
    assert degraded["severity"] == "WARNING"
    assert degraded["component"] == "transport"
    assert degraded["trace_id"] == trace_id
    assert degraded["session_id"] == "s1"
    assert degraded["metadata"]["reason_code"] == reason
    assert str(store.saved_degraded[0]["trace_id"]) == trace_id


def test_transport_degradation_mints_an_id_when_none_supplied():
    emitter, sink = make_emitter(level=Severity.WARNING)
    store = _Store()
    _runner(emitter, store=store).persist_transport_degraded_trace(
        session=_session(), wire_code="queue_overflow",
        degradation_reason="queue_overflow",
    )
    (degraded,) = of_type(sink.records, "degradation_applied")
    UUID(degraded["trace_id"])
    assert str(store.saved_degraded[0]["trace_id"]) == degraded["trace_id"]


def test_pipeline_failure_emits_degradation_before_interaction_failed():
    emitter, sink = make_emitter(level=Severity.INFO)
    store = _Store()
    trace_id = str(uuid4())
    with pytest.raises(InteractionError):
        _runner(emitter, store=store).run(
            session=_session(), audio=np.zeros(160, dtype=np.float32),
            sample_rate=16_000, trace_id=trace_id,
        )

    types = [r["event_type"] for r in sink.records]
    assert types.index("degradation_applied") < types.index("interaction_failed")
    degraded = of_type(sink.records, "degradation_applied")[0]
    assert degraded["severity"] == "WARNING" and degraded["component"] == "runner"
    assert degraded["metadata"]["reason_code"] == "pipeline_failure"
    assert degraded["trace_id"] == trace_id
    assert str(store.saved_degraded[0]["trace_id"]) == trace_id


def test_every_emitted_reason_code_is_a_degradation_reason(tmp_path):
    class BrokenAffect:
        def detect(self, audio, sample_rate):
            raise RuntimeError("x")

    emitter, sink = make_emitter(level=Severity.INFO)
    build(tmp_path, emitter, affect=BrokenAffect()).invoke(initial_state(str(uuid4())))
    runner = _runner(emitter)
    runner.persist_transport_degraded_trace(
        session=_session(), wire_code="session_timeout",
        degradation_reason="session_timeout",
    )
    runner.persist_transport_degraded_trace(
        session=_session(), wire_code="queue_overflow",
        degradation_reason="queue_overflow",
    )
    with pytest.raises(InteractionError):
        runner.run(session=_session(), audio=np.zeros(160, dtype=np.float32),
                   sample_rate=16_000)

    allowed = set(get_args(DegradationReason))
    reasons = [r["metadata"]["reason_code"]
               for r in of_type(sink.records, "degradation_applied")]
    assert len(reasons) == 4
    assert set(reasons) <= allowed
