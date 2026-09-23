import pytest

pytest.importorskip("langgraph")

import numpy as np

from pipeline.graph import build_dialogue_graph
from storage.sqlite_store import SQLiteStore
from pipeline.executor import ActionExecutor


def make_test_executor(store):
    return ActionExecutor(
        store,
        reminder_response_window_minutes=10,
        adaptive_lead_time_enabled=True,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )

class FakeSTT:
    def transcribe(self, audio, sample_rate):
        """Transcribe the supplied audio using the configured speech-to-text backend."""
        return "what should I focus on today?"


class FakeIntent:
    def classify(self, transcript):
        """Classify the supplied input using the configured classifier."""
        return "ask_status", 0.91, {}


class FakeAffect:
    def detect(self, audio, sample_rate):
        """Detect the current affect level from the supplied audio."""
        return "High"


class FailingAffect:
    def detect(self, audio, sample_rate):
        """Simulate affect detector failure for trace coverage."""
        raise RuntimeError("classifier unavailable")


class FakeLLM:
    def generate(self, prompt):
        """Generate an LLM response from the supplied conversation state and context."""
        return '{"response_text":"You have one priority task.","proposed_action":"respond"}'


def test_graph_runs_all_four_nodes_and_assembles_pending_trace(tmp_path):
    """Verify that graph runs all four nodes and assembles (but does not persist) the trace.

    Finding F1 / Phase 6 moved trace persistence out of the graph and into
    InteractionRunner, which writes only after TTS onset (see
    tests/unit/pipeline/test_interaction.py for that persistence-timing
    coverage). The graph's output node now only assembles `pending_trace`
    into the returned state; asserting against the store here would be
    testing the pre-Phase-6 architecture.
    """
    store = SQLiteStore(str(tmp_path / "test.db"))
    store.ensure_user("u1")
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=FakeIntent(), llm=FakeLLM(), store=store, affect_detector=FakeAffect(),
        confidence_threshold=0.60, context_top_k=5, deadline_proximity_hours=2,
        grace_window_minutes=15, default_lead_time=15,
        executor=make_test_executor(store),
    )
    result = graph.invoke({
        "session_id": "s1", "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32), "sample_rate": 16000,
    })
    assert result["intent"] == "ask_status"
    assert result["policy_rule"] == "n/a"
    assert result["final_response"] == "You have one priority task."
    payload = result["response_payload"]
    assert set(payload) == {
        "type", "session_id", "tts_text", "state_tag", "policy_rule", "lead_time_min"
    }
    assert payload["type"] == "response"
    assert payload["session_id"] == "s1"
    assert payload["tts_text"] == "You have one priority task."
    assert payload["policy_rule"] == "n/a"
    assert payload["state_tag"] == "speaking"

    pending_trace = result["pending_trace"]
    # pending_trace keeps trace_id as a UUID (for DecisionTraceRecord(**pending_trace)
    # construction in InteractionRunner); state["trace_id"] is the stringified form.
    assert str(pending_trace["trace_id"]) == result["trace_id"]
    assert pending_trace["policy_rule"] == "n/a"
    assert pending_trace["deadline_proximity"] == "n/a"
    assert pending_trace["reminder_outcome"] == "n/a"
    assert pending_trace["degradation_reason"] is None
    assert pending_trace["network_event"] is None
    # latency_ms / latency_basis are added later by InteractionRunner, after
    # TTS onset — they don't exist on the graph's pending_trace yet.
    assert "latency_ms" not in pending_trace
    assert "latency_basis" not in pending_trace

    # The graph itself must never persist a trace — only InteractionRunner
    # does, and only after TTS (finding F1 / Phase 6).
    assert store.list_decision_traces("u1") == []


def test_graph_records_stage_timings_for_both_parallel_branches(tmp_path):
    """F5 regression: the START -> node1_stt / START -> affect fan-out must not
    crash, and both branches' durations must survive in the same superstep.

    This fails on a plain (non-reducer) stage_timings_s key with LangGraph's
    InvalidUpdateError, since node1_stt and affect both write it from START in the
    same step. It is the regression guard called out in the Phase 1 exit criteria.
    """
    store = SQLiteStore(str(tmp_path / "test.db"))
    store.ensure_user("u-timings")
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=FakeIntent(), llm=FakeLLM(), store=store,
        affect_detector=FakeAffect(), confidence_threshold=0.60, context_top_k=5,
        deadline_proximity_hours=2, grace_window_minutes=15, default_lead_time=15,
        executor=make_test_executor(store),
    )
    result = graph.invoke({
        "session_id": "s-timings", "user_id": "u-timings",
        "audio": np.zeros(160, dtype=np.float32), "sample_rate": 16000,
    })
    stage_timings = result["stage_timings_s"]
    assert "stt" in stage_timings
    assert "affect" in stage_timings
    assert stage_timings["stt"] >= 0.0
    assert stage_timings["affect"] >= 0.0


def test_graph_records_affect_degradation_reason_for_fallback(tmp_path):
    """Verify that a fallback Low affect result is distinguishable in the pending trace.

    See the note on test_graph_runs_all_four_nodes_and_assembles_pending_trace:
    the graph assembles pending_trace but InteractionRunner is the only writer
    (finding F1 / Phase 6), so this asserts against result["pending_trace"]
    rather than the store.
    """
    store = SQLiteStore(str(tmp_path / "test.db"))
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=FakeIntent(), llm=FakeLLM(), store=store,
        affect_detector=FailingAffect(), confidence_threshold=0.60, context_top_k=5,
        deadline_proximity_hours=2, grace_window_minutes=15, default_lead_time=15,
        executor=make_test_executor(store),
    )
    result = graph.invoke({
        "session_id": "s-fallback", "user_id": "u-fallback",
        "audio": np.zeros(160, dtype=np.float32), "sample_rate": 16000,
    })
    assert result["affect_level"] == "Low"
    assert result["degradation_reason"] == "affect_detector_failure"
    pending_trace = result["pending_trace"]
    assert pending_trace["affect_level"] == "Low"
    assert pending_trace["degradation_reason"] == "affect_detector_failure"
    assert store.list_decision_traces("u-fallback") == []


class RecordingExecutor:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    def execute(self, state):
        self.calls.append(dict(state))
        return self.delegate.execute(state)


def _phase3_executor(store):
    from pipeline.executor import ActionExecutor

    return ActionExecutor(
        store,
        reminder_response_window_minutes=10,
        adaptive_lead_time_enabled=True,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )


def test_graph_routes_executable_intent_through_executor_before_llm(tmp_path):
    store = SQLiteStore(str(tmp_path / "executor-order.db"))
    store.ensure_user("u-exec")
    recorder = RecordingExecutor(_phase3_executor(store))

    class ActionSTT(FakeSTT):
        def transcribe(self, audio, sample_rate):
            return "add a task"

    class ActionIntent(FakeIntent):
        def classify(self, transcript):
            return "add_task", 0.95, {"title": "write report"}

    class OrderLLM(FakeLLM):
        def __init__(self):
            self.observed = None

        def generate(self, prompt):
            self.observed = prompt
            return '{"response_text":"I can help with that.","proposed_action":"respond"}'

    llm = OrderLLM()
    graph = build_dialogue_graph(
        stt=ActionSTT(),
        intent_classifier=ActionIntent(),
        llm=llm,
        store=store,
        affect_detector=FakeAffect(),
        confidence_threshold=0.60,
        context_top_k=5,
        deadline_proximity_hours=2,
        grace_window_minutes=15,
        default_lead_time=15,
        executor=recorder,
    )

    result = graph.invoke({
        "session_id": "s-exec",
        "user_id": "u-exec",
        "audio": np.zeros(160, dtype=np.float32),
        "sample_rate": 16000,
    })

    assert recorder.calls
    assert result["execution_outcome"]["succeeded"] is True
    retrieved_context = llm.observed.split("Retrieved context:", 1)[1]
    assert '"tasks": []' in retrieved_context
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT title FROM tasks WHERE user_id = ?", ("u-exec",)
        ).fetchone()
    assert row[0] == "write report"


def test_graph_bypasses_executor_for_low_confidence_clarification(tmp_path):
    store = SQLiteStore(str(tmp_path / "clarify.db"))
    store.ensure_user("u-clarify")
    recorder = RecordingExecutor(_phase3_executor(store))

    class UnclearIntent(FakeIntent):
        def classify(self, transcript):
            return "add_task", 0.20, {"title": "should not execute"}

    graph = build_dialogue_graph(
        stt=FakeSTT(),
        intent_classifier=UnclearIntent(),
        llm=FakeLLM(),
        store=store,
        affect_detector=FakeAffect(),
        confidence_threshold=0.60,
        context_top_k=5,
        deadline_proximity_hours=2,
        grace_window_minutes=15,
        default_lead_time=15,
        executor=recorder,
    )

    result = graph.invoke({
        "session_id": "s-clarify",
        "user_id": "u-clarify",
        "audio": np.zeros(160, dtype=np.float32),
        "sample_rate": 16000,
    })

    assert recorder.calls == []
    assert "execution_outcome" not in result
    assert result["proposed_action"] == "clarify"
    assert result["policy_rule"] == "n/a"
