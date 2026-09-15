from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("langgraph")

from pipeline.graph import build_dialogue_graph
from storage.sqlite_store import SQLiteStore


class FakeSTT:
    def transcribe(self, audio, sample_rate):
        """Transcribe the supplied audio using the configured speech-to-text backend."""
        return "please remind me about my task"


class FakeIntent:
    def classify(self, transcript):
        """Classify the supplied input using the configured classifier."""
        return "dismiss_reminder", 0.94, {}


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
    )
    result = graph.invoke({
        "session_id": "s1",
        "user_id": "u1",
        "audio": np.zeros(160, dtype=np.float32),
        "sample_rate": 16000,
    })
    assert result["transcript"]
    assert result["intent"] == "dismiss_reminder"
    assert result["policy_rule"] in {"R4", "R5"}
    assert result["final_response"]
    pending_trace = result["pending_trace"]
    # pending_trace keeps trace_id as a UUID (for DecisionTraceRecord(**pending_trace)
    # construction in InteractionRunner); state["trace_id"] is the stringified form.
    assert str(pending_trace["trace_id"]) == result["trace_id"]
    assert pending_trace["policy_rule"] == result["policy_rule"]
    assert pending_trace["intent_confidence"] == 0.94
    assert store.list_decision_traces("u1") == []
