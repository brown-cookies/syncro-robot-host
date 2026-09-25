"""InteractionRunner: the single owner of one complete interaction's lifecycle
(finding F3).

Before this module, `scripts/run_wp103.py` was the only code performing the
full capture -> graph -> TTS -> playback -> trace sequence, using print/
try-except rather than a reusable, testable unit. WP-105's WebSocket handler
needs the identical sequence with a different audio source, a different sink,
and a different failure channel; without one shared owner the handler would
become a second, drifting copy of that sequence (arch review F3).

Phase 6 (F1) completes the trace ownership boundary: the graph output node
assembles a `pending_trace`, while this runner alone adds final latency fields,
validates the completed `DecisionTraceRecord`, ensures the user exists, and
persists the trace after TTS timing is observable.

Phase 7 (F4) makes that boundary executable: adapter/node failures are mapped
to a stable application-level wire code before they leave the runner. Degraded
trace persistence remains Phase 8; this phase only establishes failure
classification and boundary behavior.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import monotonic, time
from typing import Any, Callable, cast
from uuid import uuid4

import numpy as np

from adapters.llm.intent_classifier import IntentClassifierError
from adapters.llm.ollama_adapter import LLMAdapterError
from adapters.stt.whisper_adapter import STTAdapterError
from adapters.tts.piper_adapter import TTSAdapterError
from pipeline.contracts import DecisionTraceRecord

from pipeline.graph import invoke_dialogue


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Everything the runner needs about one interaction besides the audio.

    `wake_word_detected_at` and `clock_offset_ms` are forward-looking: no
    caller in this codebase supplies non-None values for either yet (WP-107's
    wake-word integration and WP-105's clock-sync handshake are both still
    ahead). Every real caller today builds a SessionContext with both left at
    their default of `None`, so `InteractionRunner.run` always resolves
    `latency_basis` to `"host_observed_only"` in practice; the
    `"wake_word_to_tts"` branch exists and is unit-tested, but its exact
    translation from the edge's clock into this runner's `clock()` domain is
    WP-105/WP-107's responsibility to pin down, not this phase's.
    """

    session_id: str
    user_id: str
    started_monotonic: float
    wake_word_detected_at: int | None = None  # edge-clock epoch ms, SPEC 7.3
    clock_offset_ms: float | None = None


@dataclass(frozen=True, slots=True)
class InteractionResult:
    """What one full interaction produced, independent of any transport."""

    session_id: str
    trace_id: str
    response_payload: dict[str, Any]
    tts_audio: np.ndarray  # 16 kHz int16 mono, after resampling (S5)
    tts_sample_rate: int
    stage_timings_s: dict[str, float]
    latency_ms: float
    latency_basis: str
    # Set when the interaction completed but degraded (e.g. "tts_timeout").
    # In that case `tts_audio` is empty and the edge falls back to the text
    # in `response_payload["tts_text"]`.
    degradation_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FailureDisposition:
    """Stable classification for one interaction-boundary failure."""

    stage: str
    wire_code: str
    degradation_reason: str | None
    trace_required: bool


class InteractionError(RuntimeError):
    """Raised when a failure crosses the interaction boundary.

    The original exception remains available as ``cause`` for diagnostics,
    while the remaining fields form the stable application-level contract.
    """

    def __init__(
        self,
        stage: str,
        cause: BaseException,
        *,
        wire_code: str,
        degradation_reason: str | None,
        trace_required: bool,
    ) -> None:
        super().__init__(f"interaction failed at stage {stage!r}: {cause}")
        self.stage = stage
        self.cause = cause
        self.wire_code = wire_code
        self.degradation_reason = degradation_reason
        self.trace_required = trace_required


# Central F4 mapping: transport code consumes the stable wire code rather than
# importing adapter-specific exception classes. Specific adapter errors precede
# the generic node/runtime fallbacks.
_FAILURE_MAP: tuple[tuple[type[Exception], str, str, str | None, bool], ...] = (
    (STTAdapterError, "stt", "malformed_audio", "pipeline_failure", True),
    (IntentClassifierError, "intent", "pipeline_failure", "pipeline_failure", True),
    (LLMAdapterError, "llm", "pipeline_failure", "pipeline_failure", True),
    (TTSAdapterError, "tts", "pipeline_failure", "pipeline_failure", True),
    (ValueError, "pipeline", "pipeline_failure", "pipeline_failure", True),
    (RuntimeError, "pipeline", "pipeline_failure", "pipeline_failure", True),
)


class InteractionRunner:
    """Owns one interaction end to end: graph -> TTS -> resample -> trace.

    `graph` is a compiled dialogue graph (`build_dialogue_graph`'s return
    value, or a fake exposing the same `.invoke(dict) -> dict` shape used by
    `pipeline.graph.invoke_dialogue`). `resampler` matches
    `audio.resample.to_pcm16_16k`'s signature,
    `(audio: np.ndarray, rate: int) -> np.ndarray`. `clock` is injectable so
    tests can control elapsed-time readings deterministically without real
    sleeps; it defaults to `time.monotonic`, matching every other timing value
    already produced by `pipeline.graph`.
    """

    def __init__(
        self,
        *,
        graph: Any,
        store: Any,
        tts: Any,
        resampler: Callable[[np.ndarray, int], np.ndarray],
        clock: Callable[[], float] = monotonic,
        clock_ms: Callable[[], float] | None = None,
        tts_timeout_s: float | None = None,
        console: Callable[[str], None] = print,
    ) -> None:
        self._graph = graph
        self._store = store
        self._tts = tts
        self._resampler = resampler
        self._clock = clock
        self._clock_ms = clock_ms or (lambda: time() * 1000.0)
        self._tts_timeout_s = tts_timeout_s
        self._console = console
        self._tts_executor: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
            if tts_timeout_s is not None
            else None
        )
        self._tts_future: Future[tuple[np.ndarray, int]] | None = None
        self._tts_lock = Lock()

    def _synthesize(self, text: str) -> tuple[np.ndarray, int] | None:
        """Synthesize `text`, or return None if the TTS timeout is reached.

        Piper must not be called concurrently. The runner owns one single-worker
        executor for its whole lifetime and tracks the submitted future. A timed
        out synthesis cannot be cancelled safely, so a later interaction that
        arrives while that future is still running degrades to the text fallback
        without submitting another synthesis job.
        Adapter errors propagate unchanged to the F4 failure mapping.
        """
        if self._tts_timeout_s is None:
            return self._tts.synthesize(text)

        assert self._tts_executor is not None
        with self._tts_lock:
            if self._tts_future is not None:
                if not self._tts_future.done():
                    return None
                self._tts_future = None
            future = self._tts_executor.submit(self._tts.synthesize, text)
            self._tts_future = future

        try:
            return future.result(timeout=self._tts_timeout_s)
        except FutureTimeoutError:
            return None
        finally:
            with self._tts_lock:
                if self._tts_future is future and future.done():
                    self._tts_future = None

    def close(self) -> None:
        """Release the runner-owned TTS executor during process/component shutdown."""
        if self._tts_executor is None:
            return
        self._tts_executor.shutdown(wait=False, cancel_futures=True)
        self._tts_executor = None


    def run(self, *, session: SessionContext, audio: np.ndarray, sample_rate: int) -> InteractionResult:
        """Run one full interaction and return its result.

        All graph, adapter, and runner-stage failures are translated into
        ``InteractionError`` before crossing this boundary. Trace persistence
        still occurs only after TTS timing is known (F1).
        """
        try:
            graph_result = invoke_dialogue(
                self._graph,
                session_id=session.session_id,
                user_id=session.user_id,
                audio=audio,
                sample_rate=sample_rate,
            )
            state: dict[str, Any] = cast(dict[str, Any], graph_result.state)

            response_payload = state.get("response_payload")
            if response_payload is None:
                raise KeyError("dialogue graph state is missing 'response_payload'")
            pending_trace_raw = state.get("pending_trace")
            if pending_trace_raw is None:
                raise KeyError(
                    "dialogue graph state is missing 'pending_trace' (finding F1 / Phase 6); "
                    "InteractionRunner cannot finalize a trace without it"
                )

            tts_started = self._clock()
            synthesized = self._synthesize(response_payload["tts_text"])
            tts_completed = self._clock()
            tts_completed_ms = self._clock_ms()

            degradation_reason: str | None = None
            if synthesized is None:
                # Item 2: forced/real TTS timeout. The interaction itself
                # completed (policy decided), so keep the full trace and mark
                # it degraded; the edge gets text and no audio.
                degradation_reason = "tts_timeout"
                tts_audio = np.zeros(0, dtype=np.int16)
                self._console(
                    "[interaction] TTS timed out - fallback channel activated "
                    f"(session={session.session_id}, timeout={self._tts_timeout_s}s)"
                )
            else:
                tts_audio_raw, tts_native_rate = synthesized
                tts_audio = self._resampler(tts_audio_raw, tts_native_rate)

            latency_ms, latency_basis = self._compute_latency(
                session,
                tts_completed_monotonic=tts_completed,
                tts_completed_epoch_ms=tts_completed_ms,
            )

            pending_trace = dict(pending_trace_raw)
            pending_trace["latency_ms"] = latency_ms
            pending_trace["latency_basis"] = latency_basis
            if degradation_reason is not None:
                pending_trace["degradation_reason"] = degradation_reason
            trace = DecisionTraceRecord(**pending_trace)
            self._store.ensure_user(trace.user_id)
            self._store.save_decision_trace(trace.model_dump(mode="json"))

            stage_timings_s = {
                **state.get("stage_timings_s", {}),
                **graph_result.stage_durations_s,
                "tts": tts_completed - tts_started,
            }

            return InteractionResult(
                session_id=session.session_id,
                trace_id=str(trace.trace_id),
                response_payload=response_payload,
                tts_audio=tts_audio,
                tts_sample_rate=16_000,
                stage_timings_s=stage_timings_s,
                latency_ms=latency_ms,
                latency_basis=latency_basis,
                degradation_reason=degradation_reason,
            )
        except InteractionError:
            raise
        except Exception as exc:  # noqa: BLE001 - interaction boundary
            disposition = self._classify_failure(exc)
            if disposition.trace_required:
                self._persist_degraded_trace(session=session, disposition=disposition)
            raise InteractionError(
                disposition.stage,
                exc,
                wire_code=disposition.wire_code,
                degradation_reason=disposition.degradation_reason,
                trace_required=disposition.trace_required,
            ) from exc

    def _persist_degraded_trace(
        self, *, session: SessionContext, disposition: FailureDisposition
    ) -> None:
        """Persist the minimal trace for an interaction that never completed normally."""
        reason = disposition.degradation_reason
        if reason not in {"pipeline_failure", "session_timeout", "queue_overflow"}:
            return
        self._store.ensure_user(session.user_id)
        self._store.save_degraded_trace(
            {
                "trace_id": uuid4(),
                "session_id": session.session_id,
                "user_id": session.user_id,
                "timestamp": datetime.now(timezone.utc),
                "degradation_reason": reason,
                "network_event": None,
                "latency_ms": 0.0,
                "latency_basis": "host_observed_only",
            }
        )

    @staticmethod
    def _classify_failure(exc: BaseException) -> FailureDisposition:
        """Map a raw failure to the stable F4 application boundary contract."""
        for exception_type, stage, wire_code, degradation_reason, trace_required in _FAILURE_MAP:
            if isinstance(exc, exception_type):
                return FailureDisposition(
                    stage=stage,
                    wire_code=wire_code,
                    degradation_reason=degradation_reason,
                    trace_required=trace_required,
                )
        return FailureDisposition(
            stage="interaction",
            wire_code="pipeline_failure",
            degradation_reason="pipeline_failure",
            trace_required=True,
        )

    def _compute_latency(
        self,
        session: SessionContext,
        *,
        tts_completed_monotonic: float,
        tts_completed_epoch_ms: float,
    ) -> tuple[float, str]:
        """Compute SPEC 12 latency using a single clock domain per basis.

        The synchronized wake-word path uses edge epoch milliseconds translated
        into host epoch milliseconds by ``clock_offset_ms``. The fallback uses
        the host monotonic clock from ``started_monotonic`` because no clock-sync
        relationship exists in that case. The current TTS adapter is blocking,
        so synthesis completion is the observable proxy for TTS onset until a
        streaming TTS boundary exists.
        """
        if session.wake_word_detected_at is not None and session.clock_offset_ms is not None:
            wake_word_on_host_clock_ms = session.wake_word_detected_at + session.clock_offset_ms
            return max(0.0, tts_completed_epoch_ms - wake_word_on_host_clock_ms), "wake_word_to_tts"
        return max(0.0, (tts_completed_monotonic - session.started_monotonic) * 1000.0), "host_observed_only"
