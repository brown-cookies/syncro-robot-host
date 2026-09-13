"""F3 regression: before this module, only scripts/run_wp103.py performed the
full capture -> graph -> TTS -> trace sequence, with no shared, testable unit.

The runner tests use a fake compiled graph so transport-free lifecycle timing
can be controlled deterministically. The real graph now returns `pending_trace`
per Phase 6, and the runner is its single normal-path trace writer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pytest

from audio.resample import to_pcm16_16k
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext


def make_pending_trace(**overrides):
    trace = {
        "trace_id": uuid4(),
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
    trace.update(overrides)
    return trace


class FakeGraph:
    """Stands in for the compiled dialogue graph. Returns the *target* Phase 6
    shape (`pending_trace` instead of a store write) since InteractionRunner is
    built against that interface now (see module docstring).
    """

    def __init__(self, *, tts_text="Sure, I can help with that.", pending_trace=None, stage_timings_s=None, call_order=None):
        self.received_state: dict | None = None
        self._tts_text = tts_text
        self._pending_trace = pending_trace if pending_trace is not None else make_pending_trace()
        self._stage_timings_s = stage_timings_s if stage_timings_s is not None else {"stt": 0.01, "affect": 0.02}
        self._call_order = call_order

    def invoke(self, state):
        self.received_state = state
        if self._call_order is not None:
            self._call_order.append("graph")
        return {
            "response_payload": {
                "type": "response",
                "session_id": state["session_id"],
                "tts_text": self._tts_text,
                "state_tag": "speaking",
                "policy_rule": "n/a",
                "lead_time_min": 15.0,
            },
            "pending_trace": self._pending_trace,
            "stage_timings_s": self._stage_timings_s,
        }


class FakeTTS:
    def __init__(self, *, audio=None, native_rate=22_050, call_order=None):
        self.audio = audio if audio is not None else np.zeros(2_205, dtype=np.float32)
        self.native_rate = native_rate
        self.calls: list[str] = []
        self._call_order = call_order

    def synthesize(self, text):
        self.calls.append(text)
        if self._call_order is not None:
            self._call_order.append("tts")
        return self.audio, self.native_rate


class FakeStore:
    def __init__(self, *, call_order=None):
        self.ensure_user_calls: list[str] = []
        self.saved_traces: list[dict] = []
        self._call_order = call_order

    def ensure_user(self, user_id):
        self.ensure_user_calls.append(user_id)

    def save_decision_trace(self, trace_dict):
        self.saved_traces.append(trace_dict)
        if self._call_order is not None:
            self._call_order.append("trace_saved")


class FakeClock:
    """Deterministic, monotonically increasing fake clock for tests."""

    def __init__(self, start: float = 0.0, step: float = 0.1):
        self._next = start
        self._step = step

    def __call__(self) -> float:
        value = self._next
        self._next += self._step
        return value


class FakeEpochClock:
    """Deterministic host epoch clock, expressed in milliseconds."""

    def __init__(self, start_ms: float = 0.0, step_ms: float = 100.0):
        self._next = start_ms
        self._step = step_ms

    def __call__(self) -> float:
        value = self._next
        self._next += self._step
        return value


def make_session(**overrides):
    fields = {
        "session_id": "s1",
        "user_id": "u1",
        "started_monotonic": 0.0,
    }
    fields.update(overrides)
    return SessionContext(**fields)


# --- exit-criteria test: runner executes a full fake interaction ---------


def test_runner_executes_a_full_fake_interaction_without_transport_code():
    graph = FakeGraph()
    tts = FakeTTS()
    store = FakeStore()
    runner = InteractionRunner(graph=graph, store=store, tts=tts, resampler=to_pcm16_16k, clock=FakeClock())

    result = runner.run(
        session=make_session(),
        audio=np.zeros(160, dtype=np.float32),
        sample_rate=16_000,
    )

    assert result.session_id == "s1"
    assert result.response_payload["tts_text"] == "Sure, I can help with that."
    assert store.saved_traces  # something was persisted


# --- runner executes graph and TTS ----------------------------------------


def test_runner_invokes_the_graph_with_the_supplied_audio_and_ids():
    graph = FakeGraph()
    runner = InteractionRunner(
        graph=graph, store=FakeStore(), tts=FakeTTS(), resampler=to_pcm16_16k, clock=FakeClock()
    )
    audio = np.ones(320, dtype=np.float32)

    runner.run(session=make_session(session_id="s-x", user_id="u-x"), audio=audio, sample_rate=16_000)

    assert graph.received_state is not None
    assert graph.received_state["session_id"] == "s-x"
    assert graph.received_state["user_id"] == "u-x"
    assert graph.received_state["sample_rate"] == 16_000
    assert np.array_equal(graph.received_state["audio"], audio)


def test_runner_synthesizes_the_graphs_response_text():
    tts = FakeTTS()
    graph = FakeGraph(tts_text="The meeting is at 3pm.")
    runner = InteractionRunner(graph=graph, store=FakeStore(), tts=tts, resampler=to_pcm16_16k, clock=FakeClock())

    runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert tts.calls == ["The meeting is at 3pm."]


# --- result contains stage timings ----------------------------------------


def test_result_contains_stage_timings_from_graph_and_from_tts():
    graph = FakeGraph(stage_timings_s={"stt": 0.011, "affect": 0.022})
    runner = InteractionRunner(
        graph=graph, store=FakeStore(), tts=FakeTTS(), resampler=to_pcm16_16k, clock=FakeClock()
    )

    result = runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert result.stage_timings_s["stt"] == 0.011
    assert result.stage_timings_s["affect"] == 0.022
    assert "dialogue_graph" in result.stage_timings_s  # from invoke_dialogue
    assert "tts" in result.stage_timings_s  # from the runner itself
    assert result.stage_timings_s["tts"] >= 0.0


# --- trace is not written before TTS --------------------------------------


def test_trace_is_written_after_tts_not_before():
    call_order: list[str] = []
    graph = FakeGraph(call_order=call_order)
    tts = FakeTTS(call_order=call_order)
    store = FakeStore(call_order=call_order)
    runner = InteractionRunner(graph=graph, store=store, tts=tts, resampler=to_pcm16_16k, clock=FakeClock())

    runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert call_order == ["graph", "tts", "trace_saved"]


def test_trace_latency_is_finalized_from_tts_timing_before_persist():
    call_order: list[str] = []

    class AdvancingTTS(FakeTTS):
        def __init__(self, clock: "SteppedClock"):
            super().__init__(call_order=call_order)
            self._clock = clock

        def synthesize(self, text):
            self.calls.append(text)
            call_order.append("tts")
            self._clock.advance(0.25)
            return self.audio, self.native_rate

    class SteppedClock(FakeClock):
        def advance(self, seconds: float) -> None:
            self._next += seconds

    clock = SteppedClock(start=10.0, step=0.0)
    graph = FakeGraph(call_order=call_order)
    tts = AdvancingTTS(clock)
    store = FakeStore(call_order=call_order)
    runner = InteractionRunner(
        graph=graph,
        store=store,
        tts=tts,
        resampler=to_pcm16_16k,
        clock=clock,
    )

    result = runner.run(
        session=make_session(started_monotonic=10.0),
        audio=np.zeros(160, dtype=np.float32),
        sample_rate=16_000,
    )

    assert result.latency_ms == 250.0
    assert store.saved_traces[0]["latency_ms"] == 250.0
    assert store.saved_traces[0]["latency_basis"] == "host_observed_only"
    assert call_order.index("tts") < call_order.index("trace_saved")


def test_ensure_user_is_called_before_saving_the_trace():
    call_order: list[str] = []
    store = FakeStore(call_order=call_order)

    class OrderedFakeStore(FakeStore):
        def ensure_user(self, user_id):
            call_order.append("ensure_user")
            super().ensure_user(user_id)

    ordered_store = OrderedFakeStore(call_order=call_order)
    runner = InteractionRunner(
        graph=FakeGraph(), store=ordered_store, tts=FakeTTS(), resampler=to_pcm16_16k, clock=FakeClock()
    )

    runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert call_order.index("ensure_user") < call_order.index("trace_saved")


# --- result contains converted TTS audio ----------------------------------


def test_result_contains_16k_int16_resampled_audio():
    native_rate = 22_050
    raw_audio = np.zeros(native_rate, dtype=np.float32)  # 1 second at Piper's native rate
    graph = FakeGraph()
    tts = FakeTTS(audio=raw_audio, native_rate=native_rate)
    runner = InteractionRunner(graph=graph, store=FakeStore(), tts=tts, resampler=to_pcm16_16k, clock=FakeClock())

    result = runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert result.tts_audio.dtype == np.int16
    assert result.tts_sample_rate == 16_000
    assert result.tts_audio.size == 16_000  # 1 second resampled to 16 kHz


# --- latency computation ---------------------------------------------------


def test_latency_defaults_to_host_observed_only_without_clock_sync():
    clock = FakeClock(start=10.0, step=0.5)
    runner = InteractionRunner(
        graph=FakeGraph(), store=FakeStore(), tts=FakeTTS(), resampler=to_pcm16_16k, clock=clock
    )
    session = make_session(started_monotonic=10.0)  # matches the clock's first reading

    result = runner.run(session=session, audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert result.latency_basis == "host_observed_only"
    assert result.latency_ms >= 0.0


def test_latency_uses_wake_word_to_tts_when_clock_sync_available():
    graph = FakeGraph()
    runner = InteractionRunner(
        graph=graph,
        store=FakeStore(),
        tts=FakeTTS(),
        resampler=to_pcm16_16k,
        clock=FakeClock(start=1_000.0),
        clock_ms=FakeEpochClock(start_ms=2_000.0),
    )
    session = make_session(wake_word_detected_at=1_850, clock_offset_ms=100)

    result = runner.run(session=session, audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert result.latency_basis == "wake_word_to_tts"
    # edge wake timestamp 1850 ms + 100 ms host offset = 1950 ms; the
    # host epoch clock is sampled at 2000 ms after synthesis completes.
    assert result.latency_ms == 50.0


def test_latency_never_goes_negative():
    runner = InteractionRunner(
        graph=FakeGraph(), store=FakeStore(), tts=FakeTTS(), resampler=to_pcm16_16k, clock=FakeClock(start=0.0)
    )
    # started_monotonic *after* the clock's first reading would otherwise
    # produce a negative interval; the runner must clamp to zero.
    session = make_session(started_monotonic=1_000.0)

    result = runner.run(session=session, audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert result.latency_ms == 0.0


# --- pending_trace validation ------------------------------------------


def test_runner_raises_a_clear_error_when_pending_trace_is_missing():
    class NoTraceGraph(FakeGraph):
        def invoke(self, state):
            update = super().invoke(state)
            del update["pending_trace"]
            return update

    runner = InteractionRunner(
        graph=NoTraceGraph(), store=FakeStore(), tts=FakeTTS(), resampler=to_pcm16_16k, clock=FakeClock()
    )

    with pytest.raises(InteractionError) as exc_info:
        runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    assert exc_info.value.wire_code == "pipeline_failure"
    assert isinstance(exc_info.value.cause, KeyError)


def test_runner_rejects_an_invalid_pending_trace():
    bad_trace = make_pending_trace()
    del bad_trace["intent"]  # DecisionTraceRecord requires this
    graph = FakeGraph(pending_trace=bad_trace)
    runner = InteractionRunner(
        graph=graph, store=FakeStore(), tts=FakeTTS(), resampler=to_pcm16_16k, clock=FakeClock()
    )

    with pytest.raises(Exception):  # pydantic.ValidationError
        runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)


# --- F4 interaction-boundary failures ------------------------------------


def test_runner_wraps_stt_adapter_failure_with_malformed_audio_wire_code():
    class FailingGraph:
        def invoke(self, state):
            from adapters.stt.whisper_adapter import STTAdapterError

            raise STTAdapterError("bad audio")

    runner = InteractionRunner(
        graph=FailingGraph(),
        store=FakeStore(),
        tts=FakeTTS(),
        resampler=to_pcm16_16k,
        clock=FakeClock(),
    )

    with pytest.raises(InteractionError) as exc_info:
        runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    error = exc_info.value
    assert error.stage == "stt"
    assert error.wire_code == "malformed_audio"
    assert error.degradation_reason is None
    assert error.trace_required is True
    assert isinstance(error.cause, RuntimeError)


def test_runner_wraps_llm_failure_with_pipeline_failure_wire_code():
    class FailingGraph:
        def invoke(self, state):
            from adapters.llm.ollama_adapter import LLMAdapterError

            raise LLMAdapterError("Ollama unavailable")

    runner = InteractionRunner(
        graph=FailingGraph(),
        store=FakeStore(),
        tts=FakeTTS(),
        resampler=to_pcm16_16k,
        clock=FakeClock(),
    )

    with pytest.raises(InteractionError) as exc_info:
        runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    error = exc_info.value
    assert error.stage == "llm"
    assert error.wire_code == "pipeline_failure"
    assert error.trace_required is True
    assert isinstance(error.cause, RuntimeError)


def test_runner_wraps_tts_failure_with_pipeline_failure_wire_code():
    class FailingTTS(FakeTTS):
        def synthesize(self, text):
            from adapters.tts.piper_adapter import TTSAdapterError

            raise TTSAdapterError("voice unavailable")

    runner = InteractionRunner(
        graph=FakeGraph(),
        store=FakeStore(),
        tts=FailingTTS(),
        resampler=to_pcm16_16k,
        clock=FakeClock(),
    )

    with pytest.raises(InteractionError) as exc_info:
        runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    error = exc_info.value
    assert error.stage == "tts"
    assert error.wire_code == "pipeline_failure"
    assert error.trace_required is True
    assert isinstance(error.cause, RuntimeError)


def test_runner_wraps_unexpected_node_value_error_without_raw_exception_leak():
    class FailingGraph:
        def invoke(self, state):
            raise ValueError("unexpected node failure")

    runner = InteractionRunner(
        graph=FailingGraph(),
        store=FakeStore(),
        tts=FakeTTS(),
        resampler=to_pcm16_16k,
        clock=FakeClock(),
    )

    with pytest.raises(InteractionError) as exc_info:
        runner.run(session=make_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000)

    error = exc_info.value
    assert error.stage == "pipeline"
    assert error.wire_code == "pipeline_failure"
    assert isinstance(error.cause, ValueError)
