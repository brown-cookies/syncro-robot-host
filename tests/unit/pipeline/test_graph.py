import pytest

pytest.importorskip("langgraph")

import numpy as np

from pipeline.graph import build_dialogue_graph
from storage.sqlite_store import SQLiteStore


class FakeSTT:
    def transcribe(self, audio, sample_rate):
        return "what should I focus on today?"


class FakeIntent:
    def classify(self, transcript):
        return "ask_status", 0.91, {}


class FakeAffect:
    def detect(self, audio, sample_rate):
        return "High"


class FakeLLM:
    def generate(self, prompt):
        return '{"response_text":"You have one priority task.","proposed_action":"respond"}'


def test_graph_runs_all_four_nodes_and_writes_trace(tmp_path):
    store = SQLiteStore(str(tmp_path / "test.db"))
    graph = build_dialogue_graph(
        stt=FakeSTT(), intent_classifier=FakeIntent(), llm=FakeLLM(), store=store, affect_detector=FakeAffect(),
        confidence_threshold=0.60, context_top_k=5, deadline_proximity_hours=2,
        grace_window_minutes=15, default_lead_time=15,
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

    traces = store.list_decision_traces("u1")
    assert len(traces) == 1
    assert traces[0]["policy_rule"] == "n/a"
    assert traces[0]["deadline_proximity"] == "n/a"
    assert traces[0]["latency_basis"] == "host_observed_only"
    assert traces[0]["reminder_outcome"] == "n/a"
    assert traces[0]["degradation_reason"] is None
    assert traces[0]["network_event"] is None
