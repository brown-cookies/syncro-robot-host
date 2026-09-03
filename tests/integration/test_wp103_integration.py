from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("langgraph")

from pipeline.graph import build_dialogue_graph
from storage.sqlite_store import SQLiteStore


class FakeSTT:
    def transcribe(self, audio, sample_rate):
        return "please remind me about my task"


class FakeIntent:
    def classify(self, transcript):
        return "dismiss_reminder", 0.94, {}


class FakeAffect:
    def detect(self, audio, sample_rate):
        return "High"


class FakeLLM:
    def generate(self, prompt):
        return '{"response_text":"I will keep the reminder focused.","proposed_action":"deliver"}'


def test_wp103_graph_runs_stt_intent_context_llm_policy_and_trace(tmp_path):
    store = SQLiteStore(str(tmp_path / "wp103.db"))
    graph = build_dialogue_graph(
        stt=FakeSTT(),
        intent_classifier=FakeIntent(),
        llm=FakeLLM(),
        store=store,
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
