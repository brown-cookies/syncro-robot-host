"""InteractionWorker: the S1 async-worker boundary (Phase 12).

Finding S1: faster-whisper, Piper, ``requests``, and ``graph.invoke`` are all
blocking, but WP-105's WebSocket handlers are coroutines. Running
`InteractionRunner.run` inline in a handler blocks the event loop for the
whole interaction, which means no other connection's `clock_sync` is
answered, every session's timeout timer stalls, and `condition_report`
frames queue up behind whichever turn happens to be running.

The review's own recommendation is the shape implemented here: one worker
thread owning the `InteractionRunner`, a bounded `queue.Queue` of
`(SessionContext, audio, sample_rate, future)`, with the (future) async
handler awaiting the future instead of calling the runner directly. This
also makes `WhisperModel` and `PiperVoice` single-threaded by construction,
which is the only concurrency contract either library is known to honour on
this hardware -- a thread *pool* here would silently violate that.

Scope note (read before wiring this into a route): this module is the
worker/queue primitive only. It does not touch `api/app.py` or
`api/ws/stream.py` -- those are Phase 14 (WP-105 transport scaffold), which
needs Phase 13's `Connection`/session-registry shape first. In particular,
`WorkerQueueFullError` is deliberately *not* translated into a
`queue_overflow` degraded trace here: only the transport layer knows the
wire/error-frame contract (SPEC's `error{queue_overflow}` frame) that
decides what happens next for a rejected submission, and turning every
overflow into a persisted trace from inside the worker would hard-code that
decision before it has been made. Phase 14 catches `WorkerQueueFullError`
and decides.
"""

from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass

import numpy as np

from pipeline.interaction import InteractionResult, InteractionRunner, SessionContext

# Sentinel telling the worker loop to exit. A private object (not None/a
# string) so it can never collide with a legitimate queued work item.
_SENTINEL = object()


class WorkerQueueFullError(RuntimeError):
    """Raised by `submit` when the bounded queue is already at capacity.

    Deliberately not a silent block: `queue.Queue.put_nowait` either
    succeeds immediately or raises immediately, and `submit` preserves that
    non-blocking contract so a caller on the asyncio event loop can never be
    stalled by a full queue (the whole point of S1).
    """


class WorkerStoppedError(RuntimeError):
    """Raised by `submit` once `stop()` has been called on this worker."""


@dataclass(frozen=True, slots=True)
class _WorkItem:
    session: SessionContext
    audio: np.ndarray
    sample_rate: int
    future: "Future[InteractionResult]"


class InteractionWorker:
    """Owns exactly one background thread that drains a bounded queue by
    calling `InteractionRunner.run` for each item.

    `submit` is the only method meant to be called from another thread (e.g.
    the asyncio event loop's thread via `loop.run_in_executor` or a plain
    synchronous call); it never blocks and never runs the pipeline itself --
    it only enqueues and hands back a `concurrent.futures.Future` that the
    caller can wait on however suits its context (blocking `.result()` from
    a script, or `asyncio.wrap_future(...)` from a coroutine).
    """

    def __init__(self, *, runner: InteractionRunner, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize must be >= 1, got {maxsize}")
        self._runner = runner
        self._queue: "queue.Queue[_WorkItem | object]" = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(
            target=self._run, name="interaction-worker", daemon=True
        )
        self._started = False
        self._accepting = True

    @property
    def runner(self) -> InteractionRunner:
        """The `InteractionRunner` this worker drains its queue into.

        Exposed read-only, alongside `queue_depth`, so a caller outside the
        worker -- the transport layer's session-timeout reaper (WP-105) --
        can reach `InteractionRunner.persist_session_timeout_trace` for a
        session that timed out before `end_audio` ever submitted it to this
        queue. Every other interaction with the runner still goes through
        `submit()`.
        """
        return self._runner

    @property
    def queue_depth(self) -> int:
        """Number of items currently waiting (approximate; S1's "single
        integer to log"). Does not count an item currently being processed.
        """
        return self._queue.qsize()

    @property
    def is_alive(self) -> bool:
        """Whether the worker thread is currently running."""
        return self._thread.is_alive()

    def start(self) -> None:
        """Start the single worker thread. Idempotent-guarded: calling this
        twice raises rather than silently spawning a second thread, since a
        second thread would violate the single-threaded-library contract
        this class exists to guarantee.
        """
        if self._started:
            raise RuntimeError("InteractionWorker.start() called more than once")
        self._started = True
        self._thread.start()

    def submit(
        self, *, session: SessionContext, audio: np.ndarray, sample_rate: int
    ) -> "Future[InteractionResult]":
        """Enqueue one interaction and return immediately.

        Never blocks: if the queue is already full this raises
        `WorkerQueueFullError` rather than waiting for room, so a caller on
        the event loop is never stalled by a saturated worker (this is the
        entire reason S1 asks for a bounded queue over an unbounded one).
        """
        if not self._accepting:
            raise WorkerStoppedError("InteractionWorker.submit() called after stop()")
        future: "Future[InteractionResult]" = Future()
        item = _WorkItem(session=session, audio=audio, sample_rate=sample_rate, future=future)
        try:
            self._queue.put_nowait(item)
        except queue.Full as exc:
            raise WorkerQueueFullError(
                f"interaction queue is full (maxsize={self._queue.maxsize}); "
                "rejecting new work instead of blocking the caller"
            ) from exc
        return future

    def stop(self, *, timeout: float | None = None) -> None:
        """Signal the worker to exit after finishing already-queued items,
        then join it.

        Graceful by construction, not by extra bookkeeping: the sentinel is
        appended to the same FIFO queue as real work, so every item queued
        before `stop()` is called is still processed before the thread
        exits. New submissions are rejected immediately once this runs.
        """
        self._accepting = False
        if not self._started:
            return
        self._queue.put(_SENTINEL)
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        """The worker loop. Runs on the single dedicated thread only."""
        while True:
            item = self._queue.get()
            try:
                if item is _SENTINEL:
                    return
                work = item
                assert isinstance(work, _WorkItem)  # narrows for type-checkers
                self._process(work)
            finally:
                self._queue.task_done()

    def _process(self, work: _WorkItem) -> None:
        """Run one interaction and route its outcome to the caller's future.

        Any exception from `InteractionRunner.run` -- including
        `InteractionError` -- is stored on the future via `set_exception`
        rather than raised here, so one failing interaction can never kill
        the worker thread and strand every subsequent queued item.
        """
        if not work.future.set_running_or_notify_cancel():
            # The caller cancelled its future before we got to it; skip the
            # (potentially expensive) actual work entirely.
            return
        try:
            result = self._runner.run(
                session=work.session, audio=work.audio, sample_rate=work.sample_rate
            )
        except BaseException as exc:  # noqa: BLE001 - must never escape this thread
            work.future.set_exception(exc)
        else:
            work.future.set_result(result)
