from __future__ import annotations
from storage.sqlite_store import SQLiteStore
from scripts import show_trace
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext
from pipeline.graph import build_dialogue_graph
from observability.factory import build_emitter
from audio.resample import to_pcm16_16k

import json
import sqlite3
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pytest

pytest.importorskip("langgraph")


pytestmark = pytest.mark.integration


class FakeSTT:
    model_name = "tiny.en"
    model_version = "stt-v1"

    def transcribe(self, audio, sample_rate):
        return "what is on my list today"


class BrokenSTT(FakeSTT):
    def transcribe(self, audio, sample_rate):
        raise RuntimeError("stt exploded")


class FakeIntent:
    model_name = "qwen-test"
    model_version = "sha256:intent"

    def classify(self, transcript):
        return ("ask_status", 0.91, {})


class FakeAffect:
    model_name = "affect-svc"
    model_version = "v-test"

    def detect(self, audio, sample_rate):
        return "Low"


class FakeLLM:
    model_name = "qwen-test"
    model_version = "sha256:llm"

    def generate(self, prompt):
        return json.dumps({"response_text": "All good.", "proposed_action": "respond"})


class FakeTTS:
    def synthesize(self, text):
        return np.zeros(160, dtype=np.float32), 16_000


AUDIO = np.zeros(160, dtype=np.float32)


class Harness:
    """A runner wired to a real log file and a real database file."""

    def __init__(self, tmp_path, *, stt=None):
        self.log_path = tmp_path / "logs" / "events.jsonl"
        self.db_path = tmp_path / "syncro.db"
        self.emitter = build_emitter(
            SimpleNamespace(
                log_level="INFO",
                log_include_text=False,
                log_output="file",
                log_file_path=str(self.log_path),
            )
        )
        self.store = SQLiteStore(str(self.db_path))
        self.store.ensure_user("u1")
        graph = build_dialogue_graph(
            stt=stt or FakeSTT(),
            intent_classifier=FakeIntent(),
            llm=FakeLLM(),
            store=self.store,
            affect_detector=FakeAffect(),
            confidence_threshold=0.60,
            context_top_k=5,
            deadline_proximity_hours=2,
            grace_window_minutes=15,
            default_lead_time=15,
            emitter=self.emitter,
        )
        self.runner = InteractionRunner(
            graph=graph,
            store=self.store,
            tts=FakeTTS(),
            resampler=to_pcm16_16k,
            emitter=self.emitter,
        )

    def run(self, **kwargs):
        session = SessionContext(
            session_id="s1", user_id="u1", started_monotonic=0.0)
        return self.runner.run(session=session, audio=AUDIO, sample_rate=16_000, **kwargs)

    def log_events(self) -> list[dict]:
        """Read the JSONL file from disk (closing the sink flushes nothing extra:
        FileSink flushes every line, so this is what an operator would see)."""
        return [json.loads(line) for line in self.log_path.read_text("utf-8").splitlines()]

    def db_rows(self) -> list[sqlite3.Row]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(
                "SELECT trace_id, session_id, user_id, latency_ms, latency_basis, "
                "degradation_reason FROM decision_trace ORDER BY timestamp"
            ).fetchall()
        finally:
            conn.close()

    def close(self) -> None:
        self.emitter.close()


@pytest.fixture
def harness(tmp_path):
    h = Harness(tmp_path)
    yield h
    h.close()


def test_every_logged_event_carries_the_persisted_decision_trace_id(harness):
    result = harness.run()

    (row,) = harness.db_rows()
    events = harness.log_events()

    assert events, "the file sink wrote nothing"
    assert {e["trace_id"] for e in events} == {row["trace_id"]}
    assert row["trace_id"] == result.trace_id
    UUID(row["trace_id"])  # a real uuid string, not an arbitrary token
    kinds = [e["event_type"] for e in events]
    assert kinds[0] == "interaction_started" and kinds[-1] == "interaction_completed"


def test_interaction_completed_latency_matches_the_persisted_row(harness):
    harness.run()

    (row,) = harness.db_rows()
    (completed,) = [
        e for e in harness.log_events() if e["event_type"] == "interaction_completed"
    ]
    assert completed["metadata"]["latency_ms"] == pytest.approx(
        row["latency_ms"])
    assert completed["metadata"]["latency_basis"] == row["latency_basis"]


def test_two_interactions_get_two_ids_and_each_event_maps_to_exactly_one_row(harness):
    first, second = harness.run(), harness.run()

    rows = harness.db_rows()
    db_ids = [r["trace_id"] for r in rows]
    assert sorted(db_ids) == sorted([first.trace_id, second.trace_id])
    assert len(set(db_ids)) == 2

    by_trace: dict[str, int] = {}
    for event in harness.log_events():
        assert event["trace_id"] in db_ids, "event with no matching decision_trace row"
        by_trace[event["trace_id"]] = by_trace.get(event["trace_id"], 0) + 1
    assert set(by_trace) == set(db_ids)
    assert len(set(by_trace.values())) == 1  # same event count per interaction


def test_a_transport_supplied_trace_id_is_used_in_the_log_and_the_database(harness):
    supplied = "5a1f3c2e-8d4b-4f6a-9c1e-0b7d2a4e6f80"
    result = harness.run(trace_id=supplied)

    (row,) = harness.db_rows()
    assert row["trace_id"] == supplied == result.trace_id
    assert {e["trace_id"] for e in harness.log_events()} == {supplied}


def test_a_failed_interaction_keeps_one_trace_id_across_log_and_degraded_row(tmp_path):
    harness = Harness(tmp_path, stt=BrokenSTT())
    try:
        with pytest.raises(InteractionError):
            harness.run()

        (row,) = harness.db_rows()
        events = harness.log_events()
        assert {e["trace_id"] for e in events} == {row["trace_id"]}
        assert row["degradation_reason"], "failure should persist a degraded trace"
        kinds = {e["event_type"] for e in events}
        assert "interaction_failed" in kinds and "interaction_completed" not in kinds
    finally:
        harness.close()


def test_show_trace_prints_the_trace_id_so_it_can_be_matched_to_the_row(harness, capsys):
    result = harness.run()
    (row,) = harness.db_rows()

    for argv in ([result.trace_id], ["--last"]):
        assert show_trace.main(["--file", str(harness.log_path), *argv]) == 0
        out = capsys.readouterr().out
        assert out.splitlines()[0] == f"# {row['trace_id']}  (ok)"
        assert "interaction_completed" in out
