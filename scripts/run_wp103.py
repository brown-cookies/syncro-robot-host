"""WP-103 live host dialogue graph runner with stage-level observability."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from composition.bootstrap import build_wp103_components
from config.settings import get_settings
from storage.decision_trace import TRACE_FIELDS

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidences"


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


def main() -> int:
    """Run the command-line entry point for this module."""
    settings = get_settings()
    try:
        graph, _store, audio_input, audio_output, tts = build_wp103_components(
            settings)
    except Exception as exc:
        print(f"[startup] FAILED: {exc}")
        return 1

    session_id = str(uuid.uuid4())
    user_id = "wp103-demo-user"
    _store.ensure_user(
        user_id,
        declared_working_window_start="08:00",
        declared_working_window_end="22:00",
    )
    wake_word_detected_at = int(__import__("time").time() * 1000)
    started_monotonic = monotonic()

    print("WP-103 live dialogue graph")
    print("[wake_word] Host wake-word model is edge-owned per SPEC; this runner simulates the received event.")
    print(
        f"[audio_capture] Recording {settings.audio_capture_seconds:.0f}s "
        "from the USB microphone -- speak now..."
    )

    print("[wake_word] Simulating edge-confirmed wake word 'syncro' for local development")
    print(
        f"[start_audio] session_id={session_id} user_id={user_id} wake_word_detected_at={wake_word_detected_at}")
    capture_started = monotonic()
    try:
        captured, sample_rate = audio_input.capture()
    except Exception as exc:
        print(f"[audio_capture] FAILED: {exc}")
        return 1
    print(
        f"[audio_capture] OK ({monotonic() - capture_started:.3f}s, sample_rate={sample_rate})")

    state: dict = {
        "session_id": session_id,
        "user_id": user_id,
        "audio": captured,
        "sample_rate": sample_rate,
        "wake_word_detected_at": wake_word_detected_at,
        "started_monotonic": started_monotonic,
    }

    print("[graph] Running Node 1 -> Node 2 -> Node 3 -> Node 4 -> output")

    try:
        for update in graph.stream(state, stream_mode="updates"):
            node_name, node_update = next(iter(update.items()))
            state.update(node_update)

            if node_name == "node1_stt":
                print(f"[node_1] transcript: {state.get('transcript', '')}")
            elif node_name == "node1_intent":
                print(
                    "[node_1] intent: "
                    f"{state.get('intent')} "
                    f"confidence={state.get('intent_confidence', 0.0):.3f}"
                )
                if state.get("slots"):
                    print(f"[node_1] slots: {state['slots']}")
            elif node_name == "node2_context":
                print(f"[node_2] context: {state.get('context', {})}")
                print(
                    f"[node_2] context IDs: {state.get('retrieved_context_ids', [])}")
            elif node_name == "node3_llm":
                print(f"[node_3] response: {state.get('draft_response', '')}")
                print(
                    f"[node_3] proposed action: {state.get('proposed_action')}")
            elif node_name == "node4_policy":
                print(f"[node_4] affect: {state.get('affect_level')}")
                print(
                    f"[node_4] deadline proximity: {state.get('deadline_proximity')}")
                print(f"[node_4] policy_rule: {state.get('policy_rule')}")
                print(f"[node_4] action: {state.get('action_taken')}")
            elif node_name == "output":
                print(
                    f"[output] response payload: {state.get('response_payload')}")
                print(f"[output] trace_id: {state.get('trace_id')}")

    except Exception as exc:
        print(f"[graph] WP-103 run FAILED: {exc}")
        return 1

    final_response = state.get("final_response")
    if not isinstance(final_response, str) or not final_response:
        print("[output] FAILED: no final_response produced")
        return 1

    print(f"[output] final response: {final_response}")

    print("[tts] Synthesizing response with Piper...")
    tts_started = monotonic()
    try:
        spoken, tts_rate = tts.synthesize(final_response)
        print(
            f"[tts] synthesis complete ({monotonic() - tts_started:.3f}s, sample_rate={tts_rate})")
    except Exception as exc:
        print(f"[tts] FAILED: {exc}")
        return 1

    print("[audio_output] Playing synthesized audio on host speakers...")
    output_started = monotonic()
    try:
        audio_output.play(spoken, sample_rate=tts_rate)
        print(f"[audio_output] OK ({monotonic() - output_started:.3f}s)")
    except Exception as exc:
        print(f"[audio_output] FAILED: {exc}")
        return 1

    summary_lines = [
        "\nWP-103 run complete",
        f"Transcript: {state.get('transcript')}",
        f"Intent: {state.get('intent')} confidence={state.get('intent_confidence', 0.0):.3f}",
        f"Policy rule: {state.get('policy_rule')}",
        f"Action: {state.get('action_taken')}",
        f"Response: {state.get('final_response')}",
        f"Trace ID: {state.get('trace_id')}",
        f"Context IDs: {state.get('retrieved_context_ids', [])}",
    ]
    for line in summary_lines:
        print(line)

    # DEL-03 evidence: pull the persisted trace back out of storage so the
    # "trace output for a live interaction" artifact isn't a manual step.
    trace_id = state.get("trace_id")
    print("\n--- DEL-03 decision trace (live interaction) ---")
    trace_record = _fetch_decision_trace(_store, user_id, trace_id)
    if trace_record is None:
        print(
            f"[trace] FAILED: no stored decision_trace row found for trace_id={trace_id}")
        return 1

    trace_lines = _render_trace_lines(trace_record)
    for line in trace_lines:
        print(line)

    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        evidence_path = EVIDENCE_DIR / f"live_run_wp103_{stamp}.txt"
        evidence_path.write_text(
            "\n".join(
                summary_lines + ["", "--- DEL-03 decision trace (live interaction) ---"] + trace_lines) + "\n",
            encoding="utf-8",
        )
        print(
            f"\n[evidence] DEL-01/DEL-03 evidence written to {evidence_path}")
    except OSError as exc:
        print(f"[evidence] WARNING: could not write evidence file: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
