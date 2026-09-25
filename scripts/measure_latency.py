"""Step 4 latency measurement: warm runs, per-stage table, honest status line.

The 3 s budget is defined END-TO-END (wake word -> TTS done), per the scope
freeze plan. This script measures it and discloses the result; it does not tune
anything.

Usage (needs Ollama, Whisper and Piper available, same as run_wp103.py):

    python -m scripts.measure_latency                 # mic, 1 warm-up + 5 runs
    python -m scripts.measure_latency --runs 8
    python -m scripts.measure_latency --audio-file sample.wav   # repeatable input

Run 0 is always discarded (warm-up). The table and status are written to
evidences/latency_table_<UTC stamp>.md.

Column definitions (all milliseconds, one row per warm run):
  wake->intent   session start (wake) -> intent classified. INCLUDES the mic
                 capture window, STT and intent classification.
  intent->policy context retrieval + LLM + policy decision. Affect runs in
                 parallel with STT/LLM and only counts here if it is slower.
  policy->TTS    everything after the policy decision: output node, TTS
                 synthesis, resample, trace write. Computed as
                 total - the two columns above, so each row sums to total.
  total          wake -> TTS done (host_observed_only, see basis).
  LLM            the LLM node alone (memo column; already inside intent->policy).
  capture        the fixed mic window (memo column; already inside wake->intent).
  basis          latency_basis from the trace. host_observed_only means the edge
                 clock-sync handshake (WP-105) is not integrated, so "wake" is
                 the host's own session start, not the edge wake-word timestamp.
  intent         Node 1's classified intent for this run (memo column).
  confidence     Node 1's self-reported intent_confidence for this run (memo
                 column). Ollama is called with no `temperature`/`seed` set
                 (adapters/llm/intent_classifier.py), so this number is not
                 fully reproducible run over run even for the same utterance.
  clarified      "yes" when this run's confidence fell below
                 intent_confidence_threshold, meaning Node 3 took the clarify
                 short-circuit (pipeline/nodes/llm.py) instead of calling the
                 LLM. This is why `LLM` reads 0 on those rows - it is the
                 documented clarify fast path, not a measurement gap. intent
                 and confidence are read back from the persisted decision
                 trace (store.list_decision_traces), matched by trace_id -
                 this script does not change InteractionResult.
"""

from __future__ import annotations

import argparse
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

TARGET_MS = 3000.0
EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidences"
BENCH_USER_ID = "latency-bench-user"


@dataclass(frozen=True)
class LatencyRow:
    run: int
    wake_to_intent_ms: float
    intent_to_policy_ms: float
    policy_to_tts_ms: float
    total_ms: float
    llm_ms: float
    capture_ms: float
    basis: str
    # Diagnostic memo fields (default None/False so existing callers/tests
    # that build a LatencyRow without them keep working). See build_row.
    intent: str | None = None
    intent_confidence: float | None = None
    clarified: bool = False

    @property
    def post_capture_ms(self) -> float:
        return max(0.0, self.total_ms - self.capture_ms)


def build_row(
    run: int,
    *,
    total_ms: float,
    capture_s: float,
    stage_timings_s: dict[str, float],
    basis: str,
    intent: str | None = None,
    intent_confidence: float | None = None,
    confidence_threshold: float | None = None,
) -> LatencyRow:
    """Split one run's total into the plan's three columns.

    ``stage_timings_s`` comes from InteractionResult (graph node timings via
    ``timed()``). Missing stages count as 0 so a partial trace still renders.

    ``intent`` and ``intent_confidence`` are optional diagnostic memo values
    for this run (main() reads them back from the persisted decision trace).
    ``clarified`` is derived here, not passed in: Node 1 (pipeline/nodes/intent.py)
    takes the clarify short-circuit exactly when intent_confidence falls below
    confidence_threshold, so that same comparison tells us whether Node 3
    (pipeline/nodes/llm.py) skipped the LLM call this run - explaining a 0 ms
    LLM stage instead of leaving it looking like missing data.
    """
    def stage(name): return float(stage_timings_s.get(name, 0.0)) * 1000.0  # noqa: E731
    capture_ms = capture_s * 1000.0
    llm_ms = stage("llm")

    # STT and affect run in parallel; STT is the front of the main path.
    graph_start_ms = max(0.0, total_ms - _graph_and_after_ms(stage_timings_s))
    wake_to_intent = graph_start_ms + stage("stt") + stage("intent")
    intent_to_policy = stage("context") + llm_ms + stage("policy")
    # Affect only lengthens the path if it outlasts STT+intent+context+LLM.
    main_path = stage("stt") + stage("intent") + stage("context") + llm_ms
    affect_overhang = max(0.0, stage("affect") - main_path)
    intent_to_policy += affect_overhang
    policy_to_tts = max(0.0, total_ms - wake_to_intent - intent_to_policy)

    return LatencyRow(
        run=run,
        wake_to_intent_ms=wake_to_intent,
        intent_to_policy_ms=intent_to_policy,
        policy_to_tts_ms=policy_to_tts,
        total_ms=total_ms,
        llm_ms=llm_ms,
        capture_ms=capture_ms,
        basis=basis,
        intent=intent,
        intent_confidence=intent_confidence,
        clarified=(
            intent_confidence is not None
            and confidence_threshold is not None
            and intent_confidence < confidence_threshold
        ),
    )


def _graph_and_after_ms(stage_timings_s: dict[str, float]) -> float:
    """Wall time from graph start to TTS done, from the runner's own timings.

    ``dialogue_graph`` is the whole graph invocation; ``tts`` is the synthesis
    that follows it. Anything before the graph (mic capture, session setup) is
    total minus this.
    """
    return (
        float(stage_timings_s.get("dialogue_graph", 0.0))
        + float(stage_timings_s.get("tts", 0.0))
    ) * 1000.0


def status_line(observed_ms: float, target_ms: float = TARGET_MS) -> str:
    achieved = observed_ms <= target_ms
    return (
        f"Target: <= {target_ms / 1000:.0f} s end-to-end | "
        f"Observed: {observed_ms / 1000:.2f} s (median of warm runs) | "
        f"Status: {'achieved' if achieved else 'not achieved'}"
    )


def render_table(
    rows: list[LatencyRow],
    *,
    target_ms: float = TARGET_MS,
    confidence_threshold: float | None = None,
) -> str:
    """Render the table. ``confidence_threshold`` is the Node 1 setting used
    for this run (``settings.intent_confidence_threshold``); passing it lets
    the clarified-run note below state the exact cutoff that was in effect.
    """
    if not rows:
        raise ValueError("no warm runs to report")

    def fmt(v): return f"{v:,.0f}"  # noqa: E731
    def fmt_conf(v): return "-" if v is None else f"{v:.2f}"  # noqa: E731
    lines = [
        "| run | wake->intent | intent->policy | policy->TTS | total | LLM | capture | intent | confidence | clarified | basis |",
        "|----:|-------------:|---------------:|------------:|------:|----:|--------:|--------|-----------:|:---------:|-------|",
    ]
    for r in rows:
        lines.append(
            f"| {r.run} | {fmt(r.wake_to_intent_ms)} | {fmt(r.intent_to_policy_ms)} | "
            f"{fmt(r.policy_to_tts_ms)} | {fmt(r.total_ms)} | {fmt(r.llm_ms)} | "
            f"{fmt(r.capture_ms)} | {r.intent or '-'} | {fmt_conf(r.intent_confidence)} | "
            f"{'yes' if r.clarified else ''} | {r.basis} |"
        )
    totals = [r.total_ms for r in rows]
    median_total = statistics.median(totals)
    lines += [
        "",
        "All values in ms. Run 0 (warm-up) discarded.",
        f"Total: median {median_total:,.0f} | min {min(totals):,.0f} | max {max(totals):,.0f}",
        f"Median LLM stage: {statistics.median(r.llm_ms for r in rows):,.0f} ms",
        f"Median excluding the fixed capture window: "
        f"{statistics.median(r.post_capture_ms for r in rows):,.0f} ms",
        "",
        f"**{status_line(median_total, target_ms)}**",
    ]
    if median_total > target_ms:
        lines += [
            "",
            "Explanation: the budget is not met. The per-stage columns show where "
            "the time goes (the LLM stage alone is the largest share, and the total "
            "also includes the mic capture window). No tuning was done in this "
            "freeze; this is measurement and disclosure only.",
        ]
    if any(r.basis == "host_observed_only" for r in rows):
        lines += [
            "",
            "Basis note: `host_observed_only` = measured from the host's session "
            "start, not from the edge wake-word timestamp (clock-sync handshake, "
            "WP-105, is not integrated).",
        ]
    clarified_runs = [r.run for r in rows if r.clarified]
    if clarified_runs:
        threshold_note = (
            f" (intent_confidence_threshold={confidence_threshold:.2f})"
            if confidence_threshold is not None
            else ""
        )
        run_list = ", ".join(str(n) for n in clarified_runs)
        lines += [
            "",
            f"Clarified-run note: run(s) {run_list} show `LLM: 0` because Node 1's "
            f"intent_confidence for that run fell below threshold{threshold_note}, so "
            "Node 3 took the clarify short-circuit (`pipeline/nodes/llm.py`) instead "
            "of calling the LLM - Node 2 context retrieval is skipped the same way "
            "(`pipeline/nodes/context.py`). This is not a measurement gap. It also is "
            "not fully reproducible run over run for the same utterance: Node 1's "
            "confidence is self-reported by the model with no `temperature`/`seed` "
            "pinned on the Ollama call (`adapters/llm/intent_classifier.py`), so an "
            "utterance whose true confidence sits near the threshold can land on "
            "either side of it on different runs.",
        ]
    return "\n".join(lines)


def _lookup_trace_classification(
    store, *, user_id: str, trace_id: str
) -> tuple[str | None, float | None]:
    """Read back the (intent, intent_confidence) that Node 1 chose for one
    run, from the decision trace InteractionRunner already persisted.

    Uses the existing ``store.list_decision_traces`` read path (see
    storage/sqlite_store.py) rather than adding a new field to
    InteractionResult, so this stays a measure_latency.py-only change.
    Returns ``(None, None)`` if the trace can't be found (e.g. a degraded
    interaction that never reached the output node), so a lookup miss
    degrades the table gracefully instead of crashing the benchmark run.
    """
    for trace in store.list_decision_traces(user_id):
        if trace.get("trace_id") == trace_id:
            return trace.get("intent"), trace.get("intent_confidence")
    return None, None


def _write_evidence(text: str) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = EVIDENCE_DIR / f"latency_table_{stamp}.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=5,
                        help="warm runs to report (default 5; one extra warm-up run is always discarded)")
    parser.add_argument(
        "--audio-file", help="WAV to use instead of the microphone (repeatable input)")
    args = parser.parse_args()

    # Heavy imports stay here so the pure table logic is importable in tests.
    from composition.bootstrap import build_host_components
    from config.settings import get_settings
    from pipeline.interaction import SessionContext

    settings = get_settings()
    print(
        f"[startup] warming {settings.llm_model!r} (composition root warms the LLM)...")
    components = build_host_components(settings)
    components.store.ensure_user(
        BENCH_USER_ID,
        declared_working_window_start="08:00",
        declared_working_window_end="22:00",
    )

    file_audio = None
    if args.audio_file:
        import soundfile as sf

        data, rate = sf.read(args.audio_file, dtype="float32")
        file_audio = (data if data.ndim == 1 else data[:, 0], int(rate))

    rows: list[LatencyRow] = []
    for run in range(args.runs + 1):  # run 0 = warm-up, discarded
        session_id = str(uuid.uuid4())
        started = monotonic()  # "wake": same instant run_wp103.py uses
        if file_audio is None:
            print(
                f"[run {run}] recording {settings.audio_capture_seconds:.0f}s -- speak now...")
            audio, rate = components.audio_input.capture()
        else:
            audio, rate = file_audio
        capture_s = monotonic() - started
        result = components.runner.run(
            session=SessionContext(
                session_id=session_id,
                user_id=BENCH_USER_ID,
                started_monotonic=started,
            ),
            audio=audio,
            sample_rate=rate,
        )
        # Node 1's intent/confidence aren't on InteractionResult, but the
        # runner already persisted them in this run's decision trace - read
        # them back rather than changing pipeline/interaction.py's contract.
        run_intent, run_confidence = _lookup_trace_classification(
            components.store, user_id=BENCH_USER_ID, trace_id=result.trace_id
        )
        row = build_row(
            run,
            total_ms=result.latency_ms,
            capture_s=capture_s,
            stage_timings_s=result.stage_timings_s,
            basis=result.latency_basis,
            intent=run_intent,
            intent_confidence=run_confidence,
            confidence_threshold=settings.intent_confidence_threshold,
        )
        tag = "warm-up, discarded" if run == 0 else "kept"
        clarified_tag = " CLARIFIED (no LLM call)" if row.clarified else ""
        conf = "-" if row.intent_confidence is None else f"{row.intent_confidence:.2f}"
        print(
            f"[run {run}] total={row.total_ms:,.0f} ms llm={row.llm_ms:,.0f} ms "
            f"intent={row.intent or '-'} confidence={conf} trace={result.trace_id} "
            f"({tag}){clarified_tag}"
        )
        if run > 0:
            rows.append(row)

    header = [
        "# SYNCRO host latency (Step 4)",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"LLM: {settings.llm_model} | STT: {settings.stt_model_size}/{settings.stt_compute_type}",
        f"Input: {'file ' + args.audio_file if args.audio_file else 'microphone'}",
        "",
    ]
    if args.audio_file:
        header += ["Note: file input, so the capture column is ~0 and not comparable to a live mic run.", ""]
    text = "\n".join(header) + render_table(
        rows, confidence_threshold=settings.intent_confidence_threshold
    )
    print("\n" + text)
    print(f"\n[evidence] {_write_evidence(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
