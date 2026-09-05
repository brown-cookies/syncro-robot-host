"""WP-103 live host dialogue graph runner with stage-level observability."""

from __future__ import annotations

import uuid
from time import monotonic

from composition.bootstrap import build_wp103_components
from config.settings import get_settings

def main() -> int:
    settings = get_settings()
    try:
        graph, _store, audio_input, audio_output, tts = build_wp103_components(settings)
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
    print(f"[start_audio] session_id={session_id} user_id={user_id} wake_word_detected_at={wake_word_detected_at}")
    capture_started = monotonic()
    try:
        captured, sample_rate = audio_input.capture()
    except Exception as exc:
        print(f"[audio_capture] FAILED: {exc}")
        return 1
    print(f"[audio_capture] OK ({monotonic() - capture_started:.3f}s, sample_rate={sample_rate})")

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
                print(f"[node_2] context IDs: {state.get('retrieved_context_ids', [])}")
            elif node_name == "node3_llm":
                print(f"[node_3] response: {state.get('draft_response', '')}")
                print(f"[node_3] proposed action: {state.get('proposed_action')}")
            elif node_name == "node4_policy":
                print(f"[node_4] affect: {state.get('affect_level')}")
                print(f"[node_4] deadline proximity: {state.get('deadline_proximity')}")
                print(f"[node_4] policy_rule: {state.get('policy_rule')}")
                print(f"[node_4] action: {state.get('action_taken')}")
            elif node_name == "output":
                print(f"[output] response payload: {state.get('response_payload')}")
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
        print(f"[tts] synthesis complete ({monotonic() - tts_started:.3f}s, sample_rate={tts_rate})")
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

    print("\nWP-103 run complete")
    print("Transcript:", state.get("transcript"))
    print("Intent:", state.get("intent"), f"confidence={state.get('intent_confidence', 0.0):.3f}")
    print("Policy rule:", state.get("policy_rule"))
    print("Action:", state.get("action_taken"))
    print("Response:", state.get("final_response"))
    print("Trace ID:", state.get("trace_id"))
    print("Context IDs:", state.get("retrieved_context_ids", []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
