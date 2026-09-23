"""S1 regression: before this module, nothing decoupled a blocking
InteractionRunner.run() call from whatever thread invoked it. These tests
use a fake runner with controllable gates instead of the real graph/TTS so
concurrency and queue-bounding behavior can be verified deterministically
and quickly, matching the fake-based style already used in
tests/unit/pipeline/test_interaction.py.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from pipeline.interaction import InteractionResult, SessionContext
from pipeline.worker import InteractionWorker, WorkerQueueFullError, WorkerStoppedError


def make_session(**overrides) -> SessionContext:
    fields = {"session_id": "s1", "user_id": "u1", "started_monotonic": 0.0}
    fields.update(overrides)
    return SessionContext(**fields)


def make_result(**overrides) -> InteractionResult:
    fields = dict(
        session_id="s1",
        trace_id="t1",
        response_payload={"tts_text": "ok"},
        tts_audio=np.zeros(10, dtype=np.int16),
        tts_sample_rate=16_000,
        stage_timings_s={},
        latency_ms=1.0,
        latency_basis="host_observed_only",
        intent="ask_status",
        slots={},
        execution_outcome=None,
    )
    fields.update(overrides)
    return InteractionResult(**fields)


AUDIO = np.zeros(10, dtype=np.float32)


class FakeRunner:
    """Stands in for InteractionRunner. Records call order and the ident of
    whatever thread called it, and can be told to gate (block) or raise for
    a specific session_id so tests can control timing precisely.
    """

    def __init__(self) -> None:
        self.calls: list[SessionContext] = []
        self.thread_idents: list[int] = []
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()
        self._gates: dict[str, threading.Event] = {}
        self._raises: dict[str, BaseException] = {}

    def block_on(self, session_id: str) -> threading.Event:
        event = threading.Event()
        self._gates[session_id] = event
        return event

    def raise_on(self, session_id: str, exc: BaseException) -> None:
        self._raises[session_id] = exc

    def run(self, *, session: SessionContext, audio: np.ndarray, sample_rate: int) -> InteractionResult:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        self.calls.append(session)
        self.thread_idents.append(threading.get_ident())
        try:
            gate = self._gates.get(session.session_id)
            if gate is not None:
                assert gate.wait(timeout=5.0), "test gate was never released"
            if session.session_id in self._raises:
                raise self._raises[session.session_id]
            return make_result(session_id=session.session_id)
        finally:
            with self._lock:
                self._active -= 1


def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# --- basic round trip -------------------------------------------------


def test_submit_returns_a_future_resolving_to_the_runners_result():
    runner = FakeRunner()
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()
    try:
        future = worker.submit(session=make_session(), audio=AUDIO, sample_rate=16_000)
        result = future.result(timeout=2.0)
        assert result.session_id == "s1"
        assert runner.calls[0].session_id == "s1"
    finally:
        worker.stop(timeout=2.0)


# --- S1's core promise: exactly one worker thread ----------------------


def test_only_one_worker_thread_ever_calls_the_runner():
    runner = FakeRunner()
    gate = runner.block_on("blocker")
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()
    try:
        worker.submit(session=make_session(session_id="blocker"), audio=AUDIO, sample_rate=16_000)
        assert _wait_until(lambda: len(runner.calls) == 1)

        f2 = worker.submit(session=make_session(session_id="s2"), audio=AUDIO, sample_rate=16_000)
        time.sleep(0.05)  # a buggy pool would start s2 early; give it the chance
        assert len(runner.calls) == 1, "second item must wait behind the blocked one"

        gate.set()
        assert f2.result(timeout=2.0).session_id == "s2"
        assert runner.max_active == 1
        assert len(set(runner.thread_idents)) == 1
    finally:
        worker.stop(timeout=2.0)


# --- queue_depth is the single integer S1 asks to be able to log -------


def test_queue_depth_counts_items_waiting_but_not_the_one_being_processed():
    runner = FakeRunner()
    gate = runner.block_on("blocker")
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()
    try:
        worker.submit(session=make_session(session_id="blocker"), audio=AUDIO, sample_rate=16_000)
        assert _wait_until(lambda: len(runner.calls) == 1)
        assert worker.queue_depth == 0  # dequeued into processing, not "waiting"

        worker.submit(session=make_session(session_id="s2"), audio=AUDIO, sample_rate=16_000)
        worker.submit(session=make_session(session_id="s3"), audio=AUDIO, sample_rate=16_000)
        assert _wait_until(lambda: worker.queue_depth == 2)

        gate.set()
        assert _wait_until(lambda: worker.queue_depth == 0)
    finally:
        worker.stop(timeout=2.0)


# --- bounded queue never blocks the caller ------------------------------


def test_submit_raises_without_blocking_when_queue_is_full():
    runner = FakeRunner()
    gate = runner.block_on("blocker")
    worker = InteractionWorker(runner=runner, maxsize=1)
    worker.start()
    try:
        worker.submit(session=make_session(session_id="blocker"), audio=AUDIO, sample_rate=16_000)
        assert _wait_until(lambda: len(runner.calls) == 1)

        worker.submit(session=make_session(session_id="fills-queue"), audio=AUDIO, sample_rate=16_000)
        assert _wait_until(lambda: worker.queue_depth == 1)

        started = time.monotonic()
        with pytest.raises(WorkerQueueFullError):
            worker.submit(session=make_session(session_id="overflow"), audio=AUDIO, sample_rate=16_000)
        elapsed = time.monotonic() - started
        assert elapsed < 0.5, "submit() must reject immediately, not wait for room"

        gate.set()
    finally:
        worker.stop(timeout=2.0)


# --- exceptions never escape the worker thread --------------------------


def test_worker_propagates_runner_exceptions_via_the_future():
    runner = FakeRunner()
    runner.raise_on("boom", ValueError("kaboom"))
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()
    try:
        future = worker.submit(session=make_session(session_id="boom"), audio=AUDIO, sample_rate=16_000)
        with pytest.raises(ValueError, match="kaboom"):
            future.result(timeout=2.0)
    finally:
        worker.stop(timeout=2.0)


def test_one_failing_interaction_does_not_strand_later_queued_items():
    runner = FakeRunner()
    runner.raise_on("boom", RuntimeError("bang"))
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()
    try:
        f1 = worker.submit(session=make_session(session_id="boom"), audio=AUDIO, sample_rate=16_000)
        with pytest.raises(RuntimeError):
            f1.result(timeout=2.0)

        f2 = worker.submit(session=make_session(session_id="fine"), audio=AUDIO, sample_rate=16_000)
        assert f2.result(timeout=2.0).session_id == "fine"
    finally:
        worker.stop(timeout=2.0)


# --- shutdown ------------------------------------------------------------


def test_stop_drains_already_queued_items_before_the_thread_exits():
    runner = FakeRunner()
    gate = runner.block_on("blocker")
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()

    f1 = worker.submit(session=make_session(session_id="blocker"), audio=AUDIO, sample_rate=16_000)
    f2 = worker.submit(session=make_session(session_id="s2"), audio=AUDIO, sample_rate=16_000)
    assert _wait_until(lambda: worker.queue_depth == 1)

    releaser = threading.Thread(target=lambda: (time.sleep(0.05), gate.set()))
    releaser.start()
    worker.stop(timeout=2.0)
    releaser.join()

    assert worker.is_alive is False
    assert f1.result(timeout=0).session_id == "blocker"
    assert f2.result(timeout=0).session_id == "s2"


def test_submit_after_stop_raises_worker_stopped_error():
    runner = FakeRunner()
    worker = InteractionWorker(runner=runner, maxsize=4)
    worker.start()
    worker.stop(timeout=2.0)

    with pytest.raises(WorkerStoppedError):
        worker.submit(session=make_session(), audio=AUDIO, sample_rate=16_000)


def test_stop_before_start_does_not_raise():
    worker = InteractionWorker(runner=FakeRunner(), maxsize=4)
    worker.stop(timeout=2.0)  # must not hang or raise even though start() never ran
    assert worker.is_alive is False


# --- misuse guards ---------------------------------------------------------


def test_start_called_twice_raises():
    worker = InteractionWorker(runner=FakeRunner(), maxsize=4)
    worker.start()
    try:
        with pytest.raises(RuntimeError):
            worker.start()
    finally:
        worker.stop(timeout=2.0)


def test_maxsize_must_be_at_least_one():
    with pytest.raises(ValueError):
        InteractionWorker(runner=FakeRunner(), maxsize=0)
