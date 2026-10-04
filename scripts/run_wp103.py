"""WP-103 live host dialogue graph runner with stage-level observability.

Phase 10 migration (SYNCRO architecture-fixing plan): all interaction
orchestration -- graph invocation, TTS synthesis, audio resampling, latency
computation, trace persistence, and failure classification -- now lives in
`pipeline.interaction.InteractionRunner` (findings F3/F1/F4, Phases 5-7).
This script no longer performs any of that itself; it is reduced to:
build HostComponents -> capture audio -> build SessionContext ->
`runner.run(...)` -> play the result -> report/evidence. Per-node
diagnostics (transcript, per-node affect/policy prints) that used to be
printed live while streaming the graph are intentionally gone: the
InteractionRunner boundary doesn't expose intermediate graph state to
callers (that's the point of F3 -- WP-105's transport shouldn't need
node-level internals either), but nearly all of that detail still reaches
the DEL-03 evidence block below via the persisted decision-trace row.

Two modes:
  * default: run one live interaction end to end (DEL-01) and emit the
    matching decision-trace evidence (DEL-03).
  * --dump-trace TRACE_ID: skip the live run and re-emit the DEL-03 evidence
    block for a trace_id that already exists in storage. This is the
    committed producer for that evidence block -- it does not require a
    live run to reproduce, and it is what CI/review should call to check a
    trace_id someone has quoted.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, time

from composition.bootstrap import build_host_components
from config.settings import Settings, get_settings
from pipeline.interaction import InteractionError, SessionContext
from storage.decision_trace import TRACE_FIELDS

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidences"
DEMO_USER_ID = "wp103-demo-user"


def _fetch_decision_trace(store, user_id: str, trace_id: str | None) -> dict | None:
    """Look up the stored decision-trace row for this run's trace_id."""
    if not trace_id:
        return None
    for record in store.list_decision_traces(user_id):
        if record.get("trace_id") == trace_id:
            return record
    return None


def _render_trace_lines(trace_record: dict) -> list[str]:
    """Format a decision-trace row as DEL-03 evidence lines, field by field."""
    return [f"  {field}: {trace_record.get(field)}" for field in TRACE_FIELDS]


def _write_evidence(lines: list[str], stem: str) -> Path:
    """Write a full evidence transcript to evidences/ and return its path."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_path = EVIDENCE_DIR / f"{stem}_{stamp}.txt"
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return evidence_path


def dump_trace(trace_id: str, user_id: str = DEMO_USER_ID, settings: Settings | None = None) -> int:
    """Print and persist the DEL-03 evidence block for an existing trace_id.

    Standalone: does not touch audio, STT, the LLM, or TTS, and does not go
    through InteractionRunner -- it only reads whatever decision_trace row
    is already in the configured database. Unchanged by Phase 10.
    """
    settings = settings or get_settings()
    from storage.sqlite_store import SQLiteStore

    store = SQLiteStore(settings.db_path)
    log: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        log.append(line)

    emit(
        f"--- DEL-03 decision trace dump (db={settings.db_path}, user_id={user_id!r}) ---")
    trace_record = _fetch_decision_trace(store, user_id, trace_id)
    if trace_record is None:
        emit(
            f"[trace] FAILED: no stored decision_trace row found for trace_id={trace_id}")
        return 1

    for line in _render_trace_lines(trace_record):
        emit(line)

    path = _write_evidence(log, stem=f"trace_dump_{trace_id}")
    emit(f"\n[evidence] trace dump written to {path}")
    return 0


def main() -> int:
    """Run the command-line entry point for this module."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-trace",
        metavar="TRACE_ID",
        help="Skip the live run; look up and re-emit an existing decision_trace row by trace_id.",
    )
    parser.add_argument(
        "--user-id",
        default=DEMO_USER_ID,
        help=f"user_id to run/query as (default: {DEMO_USER_ID})",
    )
    args = parser.parse_args()

    if args.dump_trace:
        return dump_trace(args.dump_trace, user_id=args.user_id)

    settings = get_settings()
    log: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        log.append(line)

    emit(
        f"[startup] Warming {settings.llm_model!r} into Ollama "
        "(cold load can take a while on first run)..."
    )
    try:
        components = build_host_components(settings)
    except Exception as exc:
        emit(f"[startup] FAILED: {exc}")
        return 1

    user_id = args.user_id
    session_id = str(uuid.uuid4())
    components.store.ensure_user(
        user_id,
        declared_working_window_start="08:00",
        declared_working_window_end="22:00",
    )
    wake_word_detected_at = int(time() * 1000)
    started_monotonic = monotonic()

    emit("WP-103 live dialogue graph")
    # Self-document the config that actually governs this run, so evidence
    # doesn't need an out-of-band note about which backend/model was live.
    import os
    classifier_path_exists = os.path.exists(settings.affect_classifier_path)
    emit(
        f"[config] affect_detector_backend={settings.affect_detector_backend!r} "
        f"affect_classifier_path={settings.affect_classifier_path!r} "
        f"(exists={classifier_path_exists}) resolved_detector={type(components.affect_detector).__name__}"
    )
    emit(
        f"[config] ollama_model={settings.llm_model!r} "
        f"stt_model_size={settings.stt_model_size!r} compute_type={settings.stt_compute_type!r}"
    )
    emit(f"[config] db_path={settings.db_path!r} user_id={user_id!r}")
    emit("[wake_word] Host wake-word model is edge-owned per SPEC; this runner simulates the received event.")
    emit(
        f"[audio_capture] Recording {settings.audio_capture_seconds:.0f}s "
        "from the USB microphone -- speak now..."
    )

    emit("[wake_word] Simulating edge-confirmed wake word 'syncro' for local development")
    emit(
        f"[start_audio] session_id={session_id} user_id={user_id} wake_word_detected_at={wake_word_detected_at}")
    capture_started = monotonic()
    try:
        captured, sample_rate = components.audio_input.capture()
    except Exception as exc:
        emit(f"[audio_capture] FAILED: {exc}")
        _write_evidence(log, stem="live_run_wp103_FAILED")
        return 1
    emit(
        f"[audio_capture] OK ({monotonic() - capture_started:.3f}s, sample_rate={sample_rate})")

    session = SessionContext(
        session_id=session_id,
        user_id=user_id,
        started_monotonic=started_monotonic,
        wake_word_detected_at=wake_word_detected_at,
    )

    emit("[interaction] Running InteractionRunner (graph -> TTS -> resample -> trace)...")
    try:
        result = components.runner.run(
            session=session, audio=captured, sample_rate=sample_rate,
        )
    except InteractionError as exc:
        emit(
            f"[interaction] FAILED at stage={exc.stage!r} wire_code={exc.wire_code!r}: {exc.cause}")
        _write_evidence(log, stem="live_run_wp103_FAILED")
        return 1

    emit(f"[interaction] response: {result.response_payload.get('tts_text', '')}")
    emit(f"[interaction] intent: {result.intent}")
    emit(f"[interaction] slots: {result.slots}")
    emit(f"[interaction] execution_outcome: {result.execution_outcome}")
    emit(f"[interaction] policy_rule: {result.response_payload.get('policy_rule')}")
    emit(f"[interaction] lead_time_min: {result.response_payload.get('lead_time_min')}")
    emit(f"[interaction] state_tag: {result.response_payload.get('state_tag')}")
    emit(f"[interaction] trace_id: {result.trace_id}")
    emit(f"[interaction] stage timings (s): {result.stage_timings_s}")
    emit(
        f"[interaction] latency_ms={result.latency_ms:.1f} basis={result.latency_basis!r}")

    emit("[audio_output] Playing synthesized audio on host speakers...")
    output_started = monotonic()
    try:
        components.audio_output.play(
            result.tts_audio, sample_rate=result.tts_sample_rate,
        )
        emit(f"[audio_output] OK ({monotonic() - output_started:.3f}s)")
    except Exception as exc:
        emit(f"[audio_output] FAILED: {exc}")
        _write_evidence(log, stem="live_run_wp103_FAILED")
        return 1

    emit("")
    emit("WP-103 run complete")
    emit(f"Response: {result.response_payload.get('tts_text', '')}")
    emit(f"Trace ID: {result.trace_id}")

    # DEL-03 evidence: pull the persisted trace back out of storage so the
    # "trace output for a live interaction" artifact isn't a manual step.
    emit("")
    emit("--- DEL-03 decision trace (live interaction) ---")
    trace_record = _fetch_decision_trace(components.store, user_id, result.trace_id)
    if trace_record is None:
        emit(
            f"[trace] FAILED: no stored decision_trace row found for trace_id={result.trace_id}")
        _write_evidence(log, stem="live_run_wp103_FAILED")
        return 1

    for line in _render_trace_lines(trace_record):
        emit(line)

    evidence_path = _write_evidence(log, stem="live_run_wp103")
    emit(
        f"\n[evidence] full run transcript + DEL-03 trace written to {evidence_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
