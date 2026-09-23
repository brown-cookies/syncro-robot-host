"""WP-104 integration coverage for the affect detector and dialogue graph."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("langgraph")

from adapters.affect import ClassifierAffectDetector
from ml.affect.artifacts import save_model_artifact
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
        executor=make_test_executor(store),
    )


class FixedAffectModel:
    """Provide a pickle-safe classifier double for graph integration coverage."""

    def predict(self, features):
        """Return one valid affect level for the integration sample."""
        assert features.shape == (1, 88)
        return np.asarray(["Moderate"], dtype=object)


def test_classifier_detector_reaches_pending_trace(monkeypatch, tmp_path):
    """Exercise the real classifier adapter through the full graph and trace boundary.

    Trace persistence is owned by InteractionRunner, after TTS onset (finding
    F1 / Phase 6) — invoking the graph directly, as this integration test
    does, must not leave a row in the store. Assert against the assembled
    `pending_trace` instead.
    """
    artifact = tmp_path / "affect_svc_v1.joblib"
    save_model_artifact(FixedAffectModel(), artifact)

    class FakeFeatures:
        elapsed_seconds = 0.001
        vector = np.zeros(88, dtype=np.float64)

    monkeypatch.setattr(
        "adapters.affect.classifier_detector.extract_features",
        lambda audio, sample_rate: FakeFeatures(),
    )
    detector = ClassifierAffectDetector(artifact)

    class FakeSTT:
        def transcribe(self, audio, sample_rate):
            """Return deterministic transcript text for the graph test."""
            return "show my overdue tasks"

    class FakeIntent:
        def classify(self, transcript):
            """Return a policy-neutral status intent for the graph test."""
            return "ask_status", 0.99, {}

    class FakeLLM:
        def generate(self, prompt):
            """Return structured response text for the graph test."""
            return '{"response_text":"You have no overdue tasks.","proposed_action":"respond"}'

    store = SQLiteStore(str(tmp_path / "syncro.db"))
    graph = build_dialogue_graph(
        stt=FakeSTT(),
        intent_classifier=FakeIntent(),
        llm=FakeLLM(),
        store=store,
        affect_detector=detector,
        confidence_threshold=0.60,
        context_top_k=5,
        deadline_proximity_hours=2,
        grace_window_minutes=15,
        default_lead_time=15,
        executor=make_test_executor(store),
    )

    user_id = "wp104-integration-user"
    result = graph.invoke(
        {
            "session_id": "wp104-integration-session",
            "user_id": user_id,
            "audio": np.zeros(1600, dtype=np.float32),
            "sample_rate": 16_000,
        }
    )

    assert result["affect_level"] == "Moderate"
    pending_trace = result["pending_trace"]
    assert pending_trace["affect_level"] == "Moderate"
    assert store.list_decision_traces(user_id) == []
