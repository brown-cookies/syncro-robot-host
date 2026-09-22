"""Regression tests for the Phase 14 `/v1/stream` route.

Exercises the route against a *real* `InteractionRunner`/`InteractionWorker`
(Phases 5/12) wired to fake graph/tts/store objects, matching the fake
style already established in `tests/unit/pipeline/test_interaction.py` and
`tests/unit/pipeline/test_worker.py` -- these tests are the first thing in
the codebase to prove those two phases and this one's message contracts
(`api/ws/messages.py`) actually compose into one working request/response
cycle end to end.

What these tests do *not* cover, matching this phase's own scope note:
real device-token authentication and real downlink pacing.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from api.ws import stream
from api.ws.connection import AuthenticationError, DeviceIdentity
from api.ws.session_registry import SessionRegistry
from audio.resample import to_pcm16_16k
from pipeline.interaction import InteractionRunner
from pipeline.worker import InteractionWorker, WorkerQueueFullError


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
    """Stands in for the compiled dialogue graph (same shape as
    `tests/unit/pipeline/test_interaction.py`'s fake)."""

    def __init__(self, *, tts_text="Sure, I can help with that."):
        self.received_state: dict | None = None
        self._tts_text = tts_text

    def invoke(self, state):
        self.received_state = state
        return {
            "response_payload": {
                "type": "response",
                "session_id": state["session_id"],
                "tts_text": self._tts_text,
                "state_tag": "speaking",
                "policy_rule": "n/a",
                "lead_time_min": 15.0,
            },
            "pending_trace": make_pending_trace(
                session_id=state["session_id"], user_id=state["user_id"]
            ),
            "stage_timings_s": {"stt": 0.01, "affect": 0.02},
        }


class RaisingFakeGraph:
    """Simulates a pipeline-stage failure (F4) for the error-mapping test."""

    def invoke(self, state):
        raise ValueError("simulated pipeline failure")


class FakeTTS:
    def __init__(self, *, audio=None, native_rate=16_000):
        self.audio = audio if audio is not None else np.zeros(3_200, dtype=np.float32)
        self.native_rate = native_rate

    def synthesize(self, text):
        return self.audio, self.native_rate


class FakeStore:
    def __init__(self):
        self.saved_traces: list[dict] = []
        self.saved_degraded_traces: list[dict] = []

    def ensure_user(self, user_id):
        pass

    def save_decision_trace(self, trace_dict):
        self.saved_traces.append(trace_dict)

    def save_degraded_trace(self, trace_dict):
        self.saved_degraded_traces.append(trace_dict)


class AlwaysFullWorker:
    """Stands in for a saturated `InteractionWorker` without needing a real
    thread/queue -- exercises exactly the `WorkerQueueFullError` branch
    `pipeline/worker.py`'s own docstring says Phase 14 must catch."""

    def submit(self, *, session, audio, sample_rate):
        raise WorkerQueueFullError("queue is full")


def build_test_app(graph, tts, store, **deps_overrides) -> tuple[FastAPI, InteractionWorker]:
    """Assemble a minimal app exposing only `/v1/stream`, wired to a real
    `InteractionRunner`/`InteractionWorker` over the supplied fakes.

    `deps_overrides` reaches `StreamDeps` directly -- tests use this to
    shorten `session_timeout_seconds` well below its 30s production
    default, so reaper coverage below doesn't need a real 30s wait.
    """
    runner = InteractionRunner(graph=graph, store=store, tts=tts, resampler=to_pcm16_16k)
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()

    deps = stream.StreamDeps(
        worker=worker,
        session_registry=SessionRegistry(),
        audio_sample_rate_hz=16_000,
        **deps_overrides,
    )
    app = FastAPI()
    app.include_router(stream.router)
    app.dependency_overrides[stream.get_stream_deps] = lambda: deps
    return app, worker


def build_test_app_with_deps(deps: "stream.StreamDeps") -> FastAPI:
    app = FastAPI()
    app.include_router(stream.router)
    app.dependency_overrides[stream.get_stream_deps] = lambda: deps
    return app


# --- happy path -------------------------------------------------------


def test_full_round_trip_start_audio_to_tts_audio_end():
    graph = FakeGraph()
    tts = FakeTTS(audio=np.linspace(-0.5, 0.5, 3_200, dtype=np.float32))
    store = FakeStore()
    app, worker = build_test_app(graph, tts, store)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/v1/stream") as ws:
                ws.send_json(
                    {
                        "type": "start_audio",
                        "session_id": "s1",
                        "user_id": "u1",
                        "wake_word_detected_at": 1_700_000_000_000,
                    }
                )
                assert ws.receive_json() == {"type": "ready", "session_id": "s1"}

                ws.send_bytes(b"\x00\x00" * 160)
                ws.send_bytes(b"\x00\x00" * 160)
                ws.send_json({"type": "end_audio", "session_id": "s1", "frame_count": 2})

                response = ws.receive_json()
                assert response["type"] == "response"
                assert response["session_id"] == "s1"
                assert response["tts_text"] == "Sure, I can help with that."

                # 3,200 samples of 16 kHz int16 PCM = exactly two 100 ms
                # (3,200-byte) frames (audio/resample.py's BYTES_PER_FRAME).
                assert len(ws.receive_bytes()) == 3_200
                assert len(ws.receive_bytes()) == 3_200

                assert ws.receive_json() == {
                    "type": "tts_audio_end",
                    "session_id": "s1",
                    "frame_count": 2,
                }

                # The session_id is free again immediately after a normal completion.
                ws.send_json(
                    {
                        "type": "start_audio",
                        "session_id": "s1",
                        "user_id": "u1",
                        "wake_word_detected_at": 1_700_000_000_001,
                    }
                )
                assert ws.receive_json() == {"type": "ready", "session_id": "s1"}
    finally:
        worker.stop(timeout=2.0)

    assert store.saved_traces, "a real decision trace was persisted end-to-end"
    assert graph.received_state["session_id"] == "s1"


def test_clock_sync_request_gets_a_response_with_the_echoed_timestamp():
    app, worker = build_test_app(FakeGraph(), FakeTTS(), FakeStore())
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/v1/stream") as ws:
                ws.send_json({"type": "clock_sync_request", "edge_send_ms": 1_234})
                response = ws.receive_json()
                assert response["type"] == "clock_sync_response"
                assert response["edge_send_ms"] == 1_234
                assert isinstance(response["host_recv_ms"], int)
                assert isinstance(response["host_send_ms"], int)
    finally:
        worker.stop(timeout=2.0)


# --- collision / error paths -------------------------------------------


def test_session_collision_on_same_connection_keeps_the_original_session_running():
    app, worker = build_test_app(FakeGraph(), FakeTTS(), FakeStore())
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/v1/stream") as ws:
                ws.send_json(
                    {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 1}
                )
                assert ws.receive_json()["type"] == "ready"

                ws.send_json(
                    {"type": "start_audio", "session_id": "s2", "user_id": "u1", "wake_word_detected_at": 2}
                )
                assert ws.receive_json() == {
                    "type": "error",
                    "session_id": "s2",
                    "error_code": "session_collision",
                    "message": None,
                }

                # s1 was never reset by the rejected s2 -- it can still be
                # ended normally.
                ws.send_json({"type": "end_audio", "session_id": "s1", "frame_count": 0})
                assert ws.receive_json()["session_id"] == "s1"
    finally:
        worker.stop(timeout=2.0)


def test_malformed_audio_frame_releases_the_session():
    app, worker = build_test_app(FakeGraph(), FakeTTS(), FakeStore())
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/v1/stream") as ws:
                ws.send_json(
                    {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 1}
                )
                assert ws.receive_json()["type"] == "ready"

                ws.send_bytes(b"\x00")  # 1 byte: not a whole 16-bit sample
                error = ws.receive_json()
                assert error["type"] == "error"
                assert error["session_id"] == "s1"
                assert error["error_code"] == "malformed_audio"

                # Released immediately, per the ErrorMessage contract
                # ("ends the named session on both sides").
                ws.send_json(
                    {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 2}
                )
                assert ws.receive_json()["type"] == "ready"
    finally:
        worker.stop(timeout=2.0)


def test_pipeline_failure_maps_to_a_wire_error_and_persists_a_degraded_trace():
    store = FakeStore()
    app, worker = build_test_app(RaisingFakeGraph(), FakeTTS(), store)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/v1/stream") as ws:
                ws.send_json(
                    {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 1}
                )
                assert ws.receive_json()["type"] == "ready"

                ws.send_json({"type": "end_audio", "session_id": "s1", "frame_count": 0})
                error = ws.receive_json()
                assert error["type"] == "error"
                assert error["session_id"] == "s1"
                assert error["error_code"] == "pipeline_failure"
                assert error["message"]  # some diagnostic text, exact wording not contracted
    finally:
        worker.stop(timeout=2.0)

    assert store.saved_degraded_traces
    assert store.saved_degraded_traces[0]["degradation_reason"] == "pipeline_failure"


def test_queue_overflow_reports_queue_overflow_and_still_releases_the_session():
    deps = stream.StreamDeps(
        worker=AlwaysFullWorker(), session_registry=SessionRegistry(), audio_sample_rate_hz=16_000
    )
    app = build_test_app_with_deps(deps)

    with TestClient(app) as client:
        with client.websocket_connect("/v1/stream") as ws:
            ws.send_json(
                {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 1}
            )
            assert ws.receive_json()["type"] == "ready"

            ws.send_json({"type": "end_audio", "session_id": "s1", "frame_count": 0})
            error = ws.receive_json()
            assert error["error_code"] == "queue_overflow"

            ws.send_json(
                {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 2}
            )
            assert ws.receive_json()["type"] == "ready"


# --- session-timeout reaper ---------------------------------------------


def test_session_timeout_reclaims_an_abandoned_session_and_persists_a_degraded_trace():
    store = FakeStore()
    app, worker = build_test_app(FakeGraph(), FakeTTS(), store, session_timeout_seconds=0.15)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/v1/stream") as ws:
                ws.send_json(
                    {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 1}
                )
                assert ws.receive_json()["type"] == "ready"

                # No audio_frame, no end_audio -- just wait past the
                # (test-shortened) inactivity timeout. receive_json blocks
                # until the reaper's background task sends this.
                assert ws.receive_json() == {
                    "type": "error",
                    "session_id": "s1",
                    "error_code": "session_timeout",
                    "message": None,
                }

                # session_id is free again immediately, on the same
                # connection, same as a clean end_audio completion.
                ws.send_json(
                    {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 2}
                )
                assert ws.receive_json()["type"] == "ready"
    finally:
        worker.stop(timeout=2.0)

    assert store.saved_degraded_traces
    assert store.saved_degraded_traces[0]["degradation_reason"] == "session_timeout"
    assert store.saved_degraded_traces[0]["session_id"] == "s1"
    # Never reached end_audio, so this never went through save_decision_trace.
    assert not store.saved_traces


def test_audio_frame_activity_resets_the_inactivity_timeout():
    store = FakeStore()
    app, worker = build_test_app(FakeGraph(), FakeTTS(), store, session_timeout_seconds=0.3)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/v1/stream") as ws:
                ws.send_json(
                    {"type": "start_audio", "session_id": "s1", "user_id": "u1", "wake_word_detected_at": 1}
                )
                assert ws.receive_json()["type"] == "ready"

                # Two idle gaps shorter than the timeout, each one reset
                # by a real audio_frame in between -- the reaper must not
                # fire on either gap alone.
                time.sleep(0.1)
                ws.send_bytes(b"\x00\x00" * 160)
                time.sleep(0.1)
                ws.send_bytes(b"\x00\x00" * 160)

                ws.send_json({"type": "end_audio", "session_id": "s1", "frame_count": 2})
                assert ws.receive_json()["type"] == "response"
    finally:
        worker.stop(timeout=2.0)

    assert not store.saved_degraded_traces, "activity should have prevented a timeout"


# --- authentication -----------------------------------------------------


def test_authentication_failure_closes_the_connection_without_a_ready_message():
    def always_fail(headers):
        raise AuthenticationError("no valid device token")

    deps = stream.StreamDeps(
        worker=AlwaysFullWorker(),
        session_registry=SessionRegistry(),
        audio_sample_rate_hz=16_000,
        authenticate=always_fail,
    )
    app = build_test_app_with_deps(deps)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/stream") as ws:
                ws.receive_json()


def test_default_dev_authenticate_falls_back_to_fixed_demo_identity():
    identity = stream.default_dev_authenticate({})
    assert identity == DeviceIdentity(device_id="demo-device", user_id="demo-user")


def test_default_dev_authenticate_reads_supplied_headers():
    identity = stream.default_dev_authenticate({"x-device-id": "robot-7", "x-user-id": "u42"})
    assert identity == DeviceIdentity(device_id="robot-7", user_id="u42")
