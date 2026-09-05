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


def test_dialogue_graph_runs_full_processing_path_and_trace(tmp_path):
    """Verify that dialogue graph runs full processing path and trace."""
    store = SQLiteStore(str(tmp_path / "wp103.db"))
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
    traces = store.list_decision_traces("u1")
    assert len(traces) == 1
    assert traces[0]["trace_id"] == result["trace_id"]
    assert traces[0]["policy_rule"] == result["policy_rule"]
    assert traces[0]["intent_confidence"] == 0.94
