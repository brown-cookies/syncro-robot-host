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
) -> LatencyRow:
    """Split one run's total into the plan's three columns.

    ``stage_timings_s`` comes from InteractionResult (graph node timings via
    ``timed()``). Missing stages count as 0 so a partial trace still renders.
    """
    stage = lambda name: float(stage_timings_s.get(name, 0.0)) * 1000.0  # noqa: E731
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


def render_table(rows: list[LatencyRow], *, target_ms: float = TARGET_MS) -> str:
    if not rows:
        raise ValueError("no warm runs to report")
    fmt = lambda v: f"{v:,.0f}"  # noqa: E731
    lines = [
        "| run | wake->intent | intent->policy | policy->TTS | total | LLM | capture | basis |",
        "|----:|-------------:|---------------:|------------:|------:|----:|--------:|-------|",
    ]
    for r in rows:
        lines.append(
            f"| {r.run} | {fmt(r.wake_to_intent_ms)} | {fmt(r.intent_to_policy_ms)} | "
            f"{fmt(r.policy_to_tts_ms)} | {fmt(r.total_ms)} | {fmt(r.llm_ms)} | "
            f"{fmt(r.capture_ms)} | {r.basis} |"
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
    return "\n".join(lines)


def _write_evidence(text: str) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = EVIDENCE_DIR / f"latency_table_{stamp}.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=5, help="warm runs to report (default 5; one extra warm-up run is always discarded)")
    parser.add_argument("--audio-file", help="WAV to use instead of the microphone (repeatable input)")
    args = parser.parse_args()

    # Heavy imports stay here so the pure table logic is importable in tests.
    from composition.bootstrap import build_host_components
    from config.settings import get_settings
    from pipeline.interaction import SessionContext

    settings = get_settings()
    print(f"[startup] warming {settings.llm_model!r} (composition root warms the LLM)...")
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
            print(f"[run {run}] recording {settings.audio_capture_seconds:.0f}s -- speak now...")
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
        row = build_row(
            run,
            total_ms=result.latency_ms,
            capture_s=capture_s,
            stage_timings_s=result.stage_timings_s,
            basis=result.latency_basis,
        )
        tag = "warm-up, discarded" if run == 0 else "kept"
        print(f"[run {run}] total={row.total_ms:,.0f} ms llm={row.llm_ms:,.0f} ms trace={result.trace_id} ({tag})")
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
    text = "\n".join(header) + render_table(rows)
    print("\n" + text)
    print(f"\n[evidence] {_write_evidence(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
