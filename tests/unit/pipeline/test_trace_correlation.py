"""OBS-LOG FR-O1 / verification items 1, 13, 14: one trace_id per interaction.

The id is minted once by ``InteractionRunner.run`` (or supplied by the
transport that accepted the interaction), threaded through the graph state, and
shared by every event and by the persisted trace -- decision trace on success,
degraded trace on failure. No component may mint a second one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np
import pytest

from audio.resample import to_pcm16_16k
from observability import Emitter, EventType, Severity
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext
from pipeline.nodes.output import make_output_node


class ListSink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def write(self, record: dict) -> None:
        self.records.append(record)

    def close(self) -> None:
        return None


def make_emitter() -> tuple[Emitter, ListSink]:
    sink = ListSink()
    return Emitter([sink], level=Severity.DEBUG), sink


def pending_trace(trace_id: UUID) -> dict:
    return {
        "trace_id": trace_id,
        "session_id": "s1",
        "user_id": "u1",
        "timestamp": datetime.now(timezone.utc),
        "intent": "smalltalk",
        "intent_confidence": 0.9,
        "retrieved_context_ids": [],
        "affect_level": "Low",
        "deadline_proximity": "n/a",
        "policy_rule": "n/a",
        "action_taken": "deliver",
        "lead_time_min": 15.0,
        "reminder_outcome": "n/a",
        "degradation_reason": None,
        "network_event": None,
    }


class EchoGraph:
    """Behaves like the real graph: reads the trace_id from state, never mints one."""

    def __init__(self, *, returned_trace_id: UUID | None = None) -> None:
        self.received_state: dict | None = None
        self._returned = returned_trace_id

    def invoke(self, state):
        self.received_state = state
        trace_id = self._returned or UUID(state["trace_id"])
        return {
            "response_payload": {
                "type": "response",
                "session_id": state["session_id"],
                "tts_text": "ok",
                "state_tag": "speaking",
                "policy_rule": "n/a",
                "lead_time_min": 15.0,
            },
            "pending_trace": pending_trace(trace_id),
            "stage_timings_s": {"stt": 0.01},
        }


class BoomGraph:
    def invoke(self, state):
        raise ValueError("simulated stage failure")


class FakeTTS:
    def synthesize(self, text):
        return np.zeros(160, dtype=np.float32), 16_000


class FakeStore:
    def __init__(self) -> None:
        self.saved_traces: list[dict] = []
        self.saved_degraded_traces: list[dict] = []

    def ensure_user(self, user_id):
        return None

    def save_decision_trace(self, trace):
        self.saved_traces.append(trace)

    def save_degraded_trace(self, trace):
        self.saved_degraded_traces.append(trace)


def make_session() -> SessionContext:
    return SessionContext(session_id="s1", user_id="u1", started_monotonic=0.0)


def make_runner(graph, store, emitter) -> InteractionRunner:
    return InteractionRunner(
        graph=graph, store=store, tts=FakeTTS(), resampler=to_pcm16_16k, emitter=emitter
    )


AUDIO = np.zeros(160, dtype=np.float32)


def run(runner, **kwargs):
    return runner.run(session=make_session(), audio=AUDIO, sample_rate=16_000, **kwargs)


# --- success path ---------------------------------------------------------


def test_one_trace_id_links_graph_state_events_result_and_decision_trace():
    emitter, sink = make_emitter()
    graph, store = EchoGraph(), FakeStore()

    result = run(make_runner(graph, store, emitter))

    minted = graph.received_state["trace_id"]
    UUID(minted)  # a real uuid string
    assert result.trace_id == minted
    assert str(store.saved_traces[0]["trace_id"]) == minted
    assert {r["trace_id"] for r in sink.records} == {minted}
    assert [r["event_type"] for r in sink.records] == [
        EventType.INTERACTION_STARTED.value,
        EventType.INTERACTION_COMPLETED.value,
    ]
    assert all(r["session_id"] == "s1" for r in sink.records)


def test_interaction_completed_carries_latency_for_correlation_with_the_trace():
    emitter, sink = make_emitter()
    store = FakeStore()

    result = run(make_runner(EchoGraph(), store, emitter))

    completed = sink.records[-1]
    assert completed["event_type"] == EventType.INTERACTION_COMPLETED.value
    assert completed["metadata"]["latency_ms"] == result.latency_ms
    assert completed["metadata"]["latency_basis"] == result.latency_basis
    assert store.saved_traces[0]["latency_ms"] == result.latency_ms


def test_runner_uses_the_trace_id_the_transport_supplied():
    emitter, sink = make_emitter()
    graph, store = EchoGraph(), FakeStore()
    supplied = str(uuid4())

    result = run(make_runner(graph, store, emitter), trace_id=supplied)

    assert result.trace_id == supplied
    assert graph.received_state["trace_id"] == supplied
    assert str(store.saved_traces[0]["trace_id"]) == supplied
    assert {r["trace_id"] for r in sink.records} == {supplied}


def test_each_interaction_gets_its_own_trace_id():
    emitter, _ = make_emitter()
    runner = make_runner(EchoGraph(), FakeStore(), emitter)

    assert run(runner).trace_id != run(runner).trace_id


# --- failure paths --------------------------------------------------------


def test_failure_reuses_the_trace_id_for_the_event_the_degraded_trace_and_the_error():
    emitter, sink = make_emitter()
    store = FakeStore()

    with pytest.raises(InteractionError) as caught:
        run(make_runner(BoomGraph(), store, emitter))

    trace_id = caught.value.trace_id
    assert trace_id is not None
    assert str(store.saved_degraded_traces[0]["trace_id"]) == trace_id
    assert store.saved_traces == []
    assert {r["trace_id"] for r in sink.records} == {trace_id}
    failed = sink.records[-1]
    assert failed["event_type"] == EventType.INTERACTION_FAILED.value
    assert failed["severity"] == Severity.ERROR.value
    assert failed["error"]["error_type"] == "ValueError"
    assert failed["metadata"]["degradation_reason"] == "pipeline_failure"


def test_failure_with_a_supplied_trace_id_reuses_it():
    emitter, sink = make_emitter()
    store = FakeStore()
    supplied = str(uuid4())

    with pytest.raises(InteractionError) as caught:
        run(make_runner(BoomGraph(), store, emitter), trace_id=supplied)

    assert caught.value.trace_id == supplied
    assert str(store.saved_degraded_traces[0]["trace_id"]) == supplied


def test_a_graph_that_mints_a_second_trace_id_is_rejected():
    emitter, sink = make_emitter()
    store = FakeStore()
    rogue = EchoGraph(returned_trace_id=uuid4())

    with pytest.raises(InteractionError) as caught:
        run(make_runner(rogue, store, emitter))

    assert "exactly one trace_id" in str(caught.value.cause)
    assert store.saved_traces == []  # the mismatched trace is never persisted
    assert str(store.saved_degraded_traces[0]["trace_id"]) == caught.value.trace_id


def test_a_broken_sink_does_not_change_the_interaction_result():
    class BadSink:
        def write(self, record):
            raise OSError("disk full")

        def close(self):
            return None

    emitter = Emitter([BadSink()], level=Severity.DEBUG)
    store = FakeStore()

    result = run(make_runner(EchoGraph(), store, emitter))

    assert store.saved_traces and result.trace_id
    assert emitter.failures > 0


# --- transport-originated degraded traces --------------------------------


def test_transport_degraded_trace_reuses_the_supplied_trace_id():
    store = FakeStore()
    runner = make_runner(EchoGraph(), store, make_emitter()[0])
    supplied = str(uuid4())

    runner.persist_transport_degraded_trace(
        session=make_session(),
        wire_code="queue_overflow",
        degradation_reason="queue_overflow",
        trace_id=supplied,
    )

    assert str(store.saved_degraded_traces[0]["trace_id"]) == supplied


def test_transport_degraded_trace_mints_one_only_when_none_is_supplied():
    store = FakeStore()
    runner = make_runner(EchoGraph(), store, make_emitter()[0])

    runner.persist_transport_degraded_trace(
        session=make_session(),
        wire_code="session_timeout",
        degradation_reason="session_timeout",
    )

    assert isinstance(store.saved_degraded_traces[0]["trace_id"], UUID)


# --- output node ----------------------------------------------------------


def output_state(**overrides) -> dict:
    state = {
        "trace_id": str(uuid4()),
        "session_id": "s1",
        "user_id": "u1",
        "final_response": "Done.",
        "intent": "ask_status",
        "intent_confidence": 1.0,
        "affect_level": "Low",
    }
    state.update(overrides)
    return state


def test_output_node_reads_trace_id_from_state_and_does_not_mint_its_own():
    node = make_output_node()
    state = output_state()

    first = node(state)
    second = node(state)

    assert first["trace_id"] == state["trace_id"]
    assert first["pending_trace"]["trace_id"] == UUID(state["trace_id"])
    assert second["pending_trace"]["trace_id"] == first["pending_trace"]["trace_id"]


def test_output_node_requires_a_trace_id():
    state = output_state()
    del state["trace_id"]

    with pytest.raises(RuntimeError, match="trace_id"):
        make_output_node()(state)
