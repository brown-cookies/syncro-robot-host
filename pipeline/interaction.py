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

Wrapping node/adapter failures into `InteractionError` with a wire-code mapping
is still deferred to Phase 7 (F4). The exception type is defined below so that
Phase 7 can adopt it without another shape change, but failures still propagate
as the underlying graph/TTS exceptions in this phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, time
from typing import Any, Callable, cast

import numpy as np

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


class InteractionError(RuntimeError):
    """Raised at the interaction boundary so no raw adapter/node exception
    crosses it uncategorized (finding F4).

    Not yet raised by `InteractionRunner` itself -- the centralized
    (stage, exception type) -> (wire code, degradation reason, trace-required)
    mapping that decides `wire_code` is Phase 7's job. Defined now so that
    phase is additive rather than another shape change to this module.
    """

    def __init__(self, stage: str, cause: BaseException, *, wire_code: str | None = None):
        super().__init__(f"interaction failed at stage {stage!r}: {cause}")
        self.stage = stage
        self.cause = cause
        self.wire_code = wire_code


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
    ) -> None:
        self._graph = graph
        self._store = store
        self._tts = tts
        self._resampler = resampler
        self._clock = clock
        self._clock_ms = clock_ms or (lambda: time() * 1000.0)

    def run(self, *, session: SessionContext, audio: np.ndarray, sample_rate: int) -> InteractionResult:
        """Run one full interaction and return its result.

        Trace ordering matters here and is covered by
        `tests/unit/pipeline/test_interaction.py`: the trace is written after
        TTS completes, not after the graph returns, so `latency_ms` reflects
        SPEC 12's `tts_onset_time - wake_word_detected_at`, not the graph's own
        (too-early) completion time (finding F1).
        """
        graph_result = invoke_dialogue(
            self._graph,
            session_id=session.session_id,
            user_id=session.user_id,
            audio=audio,
            sample_rate=sample_rate,
        )
        # The graph output node now returns the assembled trace without timing
        # fields. The runner completes that record after TTS timing is known.
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
        tts_audio_raw, tts_native_rate = self._tts.synthesize(response_payload["tts_text"])
        tts_completed = self._clock()
        tts_completed_ms = self._clock_ms()

        tts_audio = self._resampler(tts_audio_raw, tts_native_rate)

        latency_ms, latency_basis = self._compute_latency(
            session,
            tts_completed_monotonic=tts_completed,
            tts_completed_epoch_ms=tts_completed_ms,
        )

        pending_trace = dict(pending_trace_raw)
        pending_trace["latency_ms"] = latency_ms
        pending_trace["latency_basis"] = latency_basis
        # Validate the completed record the same way the graph's output node
        # already does today, before it becomes this module's job in Phase 6.
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
