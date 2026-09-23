from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("langgraph")

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
        return "please remind me about my task"


class FakeIntent:
    def classify(self, transcript):
        """Classify the supplied input using the configured classifier."""
        return "add_task", 0.94, {"title": "write integration test"}


class FakeAffect:
    def detect(self, audio, sample_rate):
        """Detect the current affect level from the supplied audio."""
        return "High"


class FakeLLM:
    def generate(self, prompt):
        """Generate an LLM response from the supplied conversation state and context."""
        return '{"response_text":"I will keep the reminder focused.","proposed_action":"deliver"}'


def test_dialogue_graph_runs_full_processing_path_and_assembles_trace(tmp_path):
    """Verify that dialogue graph runs the full processing path and assembles a trace.

    Trace persistence is owned by InteractionRunner, after TTS onset (finding
    F1 / Phase 6) — invoking the graph directly, as this integration test
    does, must not leave a row in the store. Assert against the assembled
    `pending_trace` instead.
    """
    store = SQLiteStore(str(tmp_path / "wp103.db"))
    store.ensure_user("u1")
    graph = build_dialogue_graph(
        stt=FakeSTT(),
        intent_classifier=FakeIntent(),
        llm=FakeLLM(),
        store=store,
        affect_detector=FakeAffect(),
        confidence_threshold=0.60,
        context_top_k=5,
        deadline_proximity_hours=2,
        grace_window_minutes=15,
        default_lead_time=15,
        executor=make_test_executor(store),
    )
    result = graph.invoke({
        "session_id": "s1",
        "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32),
        "sample_rate": 16000,
    })
    assert result["transcript"]
    assert result["intent"] == "add_task"
    assert result["policy_rule"] == "n/a"
    assert result["final_response"]
    assert result["execution_outcome"]["succeeded"] is True
    pending_trace = result["pending_trace"]
    # pending_trace keeps trace_id as a UUID (for DecisionTraceRecord(**pending_trace)
    # construction in InteractionRunner); state["trace_id"] is the stringified form.
    assert str(pending_trace["trace_id"]) == result["trace_id"]
    assert pending_trace["policy_rule"] == "n/a"
    assert pending_trace["intent_confidence"] == 0.94
    assert store.list_decision_traces("u1") == []



def _seed_pending_reminder(store, *, user_id="u1"):
    from datetime import datetime, timezone
    from uuid import uuid4

    trace_id = str(uuid4())
    store.ensure_user(user_id)
    now = datetime.now(timezone.utc)
    with store.database.connection() as conn:
        conn.execute(
            """
            INSERT INTO decision_trace(
                trace_id, session_id, user_id, timestamp, intent,
                intent_confidence, retrieved_context_ids, affect_level,
                deadline_proximity, policy_rule, action_taken, lead_time_min,
                reminder_outcome, degradation_reason, network_event,
                latency_ms, latency_basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id, "reminder-session", user_id, now.isoformat(),
                "request_summary", 0.99, "[]", "Moderate",
                "not_imminent", "R2", "defer", 15.0,
                "pending", None, None, 1.0, "host_observed_only",
            ),
        )
    return trace_id


class OutcomeAwareLLM(FakeLLM):
    def __init__(self, response):
        self.response = response
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return self.response


@pytest.mark.parametrize("intent,slots", [
    ("add_task", {"title": "phase17 integration task"}),
    ("reschedule_task", {"task_reference": "phase17 existing task", "new_deadline": "2026-09-27T10:00:00+00:00"}),
])
def test_phase17_executable_task_intents_reach_executor_then_llm(tmp_path, intent, slots):
    store = SQLiteStore(str(tmp_path / f"{intent}.db"))
    store.ensure_user("u1")
    if intent == "reschedule_task":
        task_id = store.save_task("u1", "phase17 existing task")
        assert task_id

    class Intent(FakeIntent):
        def classify(self, transcript):
            return intent, 0.95, slots

    llm = OutcomeAwareLLM(
        '{"response_text":"The requested action is complete.","proposed_action":"respond"}'
    )
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=Intent(), llm=llm,
        store=store, affect_detector=FakeAffect(), confidence_threshold=0.60,
        context_top_k=5, deadline_proximity_hours=2, grace_window_minutes=15,
        default_lead_time=15, executor=make_test_executor(store),
    )
    result = graph.invoke({
        "session_id": "s1", "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32), "sample_rate": 16000,
    })
    assert result["execution_outcome"]["succeeded"] is True
    assert result["policy_rule"] == "n/a"
    assert result["deadline_proximity"] == "n/a"
    assert result["draft_response"] == "The requested action is complete."
    assert '"succeeded": true' in llm.prompt


@pytest.mark.parametrize("intent,outcome_name", [
    ("snooze_reminder", "snoozed"),
    ("dismiss_reminder", "accepted"),
])
def test_phase17_reminder_action_intents_mutate_referenced_prior_trace(tmp_path, intent, outcome_name):
    store = SQLiteStore(str(tmp_path / f"{intent}.db"))
    trace_id = _seed_pending_reminder(store)

    class Intent(FakeIntent):
        def classify(self, transcript):
            slots = {"reference_trace_id": trace_id}
            if intent == "snooze_reminder":
                slots["snooze_minutes"] = 10
            return intent, 0.96, slots

    llm = OutcomeAwareLLM(
        '{"response_text":"The reminder action is complete.","proposed_action":"respond"}'
    )
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=Intent(), llm=llm,
        store=store, affect_detector=FakeAffect(), confidence_threshold=0.60,
        context_top_k=5, deadline_proximity_hours=2, grace_window_minutes=15,
        default_lead_time=15, executor=make_test_executor(store),
    )
    result = graph.invoke({
        "session_id": "s1", "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32), "sample_rate": 16000,
    })
    assert result["execution_outcome"]["succeeded"] is True
    assert result["execution_outcome"]["target_id"] == trace_id
    assert result["policy_rule"] == "n/a"
    assert result["deadline_proximity"] == "n/a"
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT reminder_outcome FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row[0] == outcome_name


def test_phase17_failed_executor_result_cannot_be_confirmed_by_llm(tmp_path):
    store = SQLiteStore(str(tmp_path / "failed.db"))
    store.ensure_user("u1")

    class Intent(FakeIntent):
        def classify(self, transcript):
            return "add_task", 0.96, {"title": ""}

    llm = OutcomeAwareLLM(
        '{"response_text":"I added the task for you.","proposed_action":"respond"}'
    )
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=Intent(), llm=llm,
        store=store, affect_detector=FakeAffect(), confidence_threshold=0.60,
        context_top_k=5, deadline_proximity_hours=2, grace_window_minutes=15,
        default_lead_time=15, executor=make_test_executor(store),
    )
    result = graph.invoke({
        "session_id": "s1", "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32), "sample_rate": 16000,
    })
    assert result["execution_outcome"]["succeeded"] is False
    assert result["execution_outcome"]["error_code"] == "invalid_slots"
    assert "I have not added that yet" in result["draft_response"]
    assert result["policy_rule"] == "n/a"
