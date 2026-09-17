"""Manual live test for the `/v1/stream` WebSocket route (Phase 14).

Mirrors `scripts/run_wp103.py`'s observability and evidence pattern, but
drives the interaction over a real WebSocket connection instead of calling
`InteractionRunner` in-process -- this is what actually exercises the
transport layer (session tracking, the worker queue hand-off, wire error
mapping, downlink chunking) that WP-103 deliberately bypasses.

Usage:
    1. Start the real server in one terminal:
         uvicorn api.app:app --port 8765
    2. In another terminal:
         python -m scripts.run_manual_stream                 # record 3s from mic
         python -m scripts.run_manual_stream --seconds 5
         python -m scripts.run_manual_stream some_speech.wav  # 16kHz mono PCM16 WAV
         python -m scripts.run_manual_stream --silence        # transport-only check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import websockets

from config.settings import get_settings
from storage.decision_trace import TRACE_FIELDS

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidences"
DEMO_USER_ID = "manual-stream-test-user"
SAMPLE_RATE_HZ = 16_000
# 100 ms of 16 kHz, 16-bit, mono PCM -- matches audio/resample.py
BYTES_PER_FRAME = 3_200


def _write_evidence(lines: list[str], stem: str) -> Path:
    """Write a full run transcript to evidences/, same convention as
    `scripts/run_wp103.py`'s `_write_evidence`."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = EVIDENCE_DIR / f"{stem}_{stamp}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _render_trace_lines(trace_record: dict) -> list[str]:
    """Format a decision-trace row field by field (mirrors
    `run_wp103.py`'s `_render_trace_lines` exactly, so DEL-03 evidence
    looks the same regardless of which script produced it)."""
    return [f"  {field}: {trace_record.get(field)}" for field in TRACE_FIELDS]


def _render_pipeline_breakdown(trace_record: dict) -> list[str]:
    """Group the same decision-trace fields by the graph node that
    produced them (`pipeline/graph.py`'s wiring: node1_stt -> node1_intent
    -> node2_context -> node3_llm -> [join with affect] -> node4_policy ->
    output). Same data as `_render_trace_lines`, just organized to answer
    "what did each node decide" instead of "what's in the row".

    Two nodes are listed as explicitly unavailable, not silently skipped:
    `node1_stt`'s transcript and `node3_llm`'s pre-policy draft never
    reach the persisted row at all (`TRACE_FIELDS` has no `transcript` or
    `draft_response` column) -- and `InteractionRunner`'s F3 boundary
    (Phase 5) never returns intermediate graph state to *any* caller, in
    process or over the wire, so there is no path -- not even a wire
    protocol change -- that recovers them from outside the graph itself.
    """
    return [
        "[node1_stt] transcript: not available -- not a persisted field, and "
        "InteractionRunner's F3 boundary never returns intermediate graph "
        "state to begin with (see this function's docstring)",
        f"[node1_intent] intent={trace_record.get('intent')} "
        f"intent_confidence={trace_record.get('intent_confidence')}",
        f"[node2_context] retrieved_context_ids={trace_record.get('retrieved_context_ids')}",
        f"[affect] affect_level={trace_record.get('affect_level')} "
        f"degradation_reason={trace_record.get('degradation_reason')}",
        "[node3_llm] draft_response: not available -- only node4_policy's "
        "finalized text crosses the wire, as tts_text (see [interaction] above)",
        f"[node4_policy] policy_rule={trace_record.get('policy_rule')} "
        f"deadline_proximity={trace_record.get('deadline_proximity')} "
        f"action_taken={trace_record.get('action_taken')} "
        f"lead_time_min={trace_record.get('lead_time_min')} "
        f"reminder_outcome={trace_record.get('reminder_outcome')}",
    ]


def _fetch_decision_trace_by_session(store, user_id: str, session_id: str) -> dict | None:
    """Look up the stored decision-trace row for this run's session_id.

    Filters on `session_id`, not `trace_id` -- unlike `run_wp103.py`, this
    script never learns the real `trace_id` (SPEC 8.1's `response` message
    doesn't carry it; see this module's docstring).
    """
    for record in store.list_decision_traces(user_id):
        if record.get("session_id") == session_id:
            return record
    return None


def _load_wav_as_pcm16_16k(path: str) -> bytes:
    import soundfile as sf

    data, sr = sf.read(path, dtype="int16", always_2d=False)
    if data.ndim > 1:
        data = data[:, 0]  # first channel only, if the file is stereo
    if sr != SAMPLE_RATE_HZ:
        raise SystemExit(
            f"{path} is {sr} Hz; this script expects {SAMPLE_RATE_HZ} Hz mono PCM16. "
            f"Re-export it, or drop the path and let this script record from your mic."
        )
    return data.tobytes()


def _record_from_mic(seconds: float, emit) -> bytes:
    import sounddevice as sd

    emit(
        f"[audio_capture] Recording {seconds:.1f}s from the default microphone -- speak now...")
    recording = sd.rec(int(seconds * SAMPLE_RATE_HZ),
                       samplerate=SAMPLE_RATE_HZ, channels=1, dtype="int16")
    sd.wait()
    emit("[audio_capture] OK")
    return recording.reshape(-1).tobytes()


def _play_pcm16_16k(audio_bytes: bytes, emit) -> None:
    import numpy as np
    import sounddevice as sd

    emit("[audio_output] Playing synthesized audio on host speakers...")
    samples = np.frombuffer(audio_bytes, dtype="<i2")
    sd.play(samples, samplerate=SAMPLE_RATE_HZ)
    sd.wait()
    emit("[audio_output] OK")


async def run_interaction(*, uri: str, audio_bytes: bytes, user_id: str, emit) -> tuple[str, str | None, bytes]:
    """Drive one full interaction over `/v1/stream`.

    Returns (session_id, error_code_or_None, received_tts_audio_bytes).
    """
    frames = [audio_bytes[i: i + BYTES_PER_FRAME]
              for i in range(0, len(audio_bytes), BYTES_PER_FRAME)]
    session_id = str(uuid.uuid4())

    async with websockets.connect(uri) as ws:
        edge_send_ms = int(time.time() * 1000)
        await ws.send(json.dumps({"type": "clock_sync_request", "edge_send_ms": edge_send_ms}))
        clock_sync = json.loads(await ws.recv())
        emit(f"[clock_sync] request edge_send_ms={edge_send_ms}")
        emit(f"[clock_sync] response {clock_sync}")

        wake_word_detected_at = int(time.time() * 1000)
        emit(
            f"[start_audio] session_id={session_id} user_id={user_id} wake_word_detected_at={wake_word_detected_at}")
        await ws.send(json.dumps({
            "type": "start_audio",
            "session_id": session_id,
            "user_id": user_id,
            "wake_word_detected_at": wake_word_detected_at,
        }))
        ready = json.loads(await ws.recv())
        emit(f"[start_audio] {ready}")
        if ready.get("type") != "ready":
            emit("[start_audio] FAILED: did not get ready")
            return session_id, "no_ready", b""

        emit(
            f"[uplink_audio] sending {len(frames)} frame(s), "
            f"{len(audio_bytes)} bytes ({len(audio_bytes) / (SAMPLE_RATE_HZ * 2):.2f}s of 16kHz PCM16)"
        )
        for frame in frames:
            await ws.send(frame)

        interaction_started = time.monotonic()
        await ws.send(json.dumps({"type": "end_audio", "session_id": session_id, "frame_count": len(frames)}))

        first = json.loads(await ws.recv())
        round_trip_s = time.monotonic() - interaction_started
        if first.get("type") == "error":
            emit(f"[interaction] FAILED after {round_trip_s:.3f}s: {first}")
            return session_id, first.get("error_code"), b""

        emit(f"[interaction] response received after {round_trip_s:.3f}s")
        emit(f"[interaction] tts_text: {first.get('tts_text')}")
        emit(f"[interaction] policy_rule: {first.get('policy_rule')}")
        emit(f"[interaction] state_tag: {first.get('state_tag')}")
        emit(f"[interaction] lead_time_min: {first.get('lead_time_min')}")

        tts_audio = bytearray()
        chunk_count = 0
        while True:
            message = await ws.recv()
            if isinstance(message, bytes):
                tts_audio.extend(message)
                chunk_count += 1
                continue
            emit(
                f"[downlink_audio] received {chunk_count} chunk(s), {len(tts_audio)} bytes")
            emit(f"[tts_audio_end] {message}")
            break

        return session_id, None, bytes(tts_audio)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wav_path", nargs="?",
                        help="16 kHz mono PCM16 WAV file to send")
    parser.add_argument("--seconds", type=float, default=3.0,
                        help="seconds to record from the mic (default 3)")
    parser.add_argument("--silence", action="store_true",
                        help="send silence -- transport-only check")
    parser.add_argument("--uri", default="ws://127.0.0.1:8765/v1/stream",
                        help="the /v1/stream URI to connect to")
    parser.add_argument("--user-id", default=DEMO_USER_ID,
                        help=f"user_id to run as (default: {DEMO_USER_ID})")
    parser.add_argument("--no-play", action="store_true",
                        help="don't play the returned TTS audio through speakers")
    parser.add_argument(
        "--no-trace-lookup", action="store_true",
        help="skip reading the decision_trace row back out of the server's SQLite db "
             "(only works when this script and the server share a filesystem)",
    )
    args = parser.parse_args()

    log: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        log.append(line)

    if args.silence:
        audio_bytes = b"\x00\x00" * SAMPLE_RATE_HZ  # 1 second
        emit("[audio_source] silence (1.0s) -- real STT will correctly reject this as an empty transcript")
    elif args.wav_path:
        audio_bytes = _load_wav_as_pcm16_16k(args.wav_path)
        emit(f"[audio_source] wav file: {args.wav_path}")
    else:
        audio_bytes = _record_from_mic(args.seconds, emit)
        emit("[audio_source] microphone")

    emit(f"[config] uri={args.uri!r} user_id={args.user_id!r}")

    try:
        session_id, error_code, tts_audio = asyncio.run(
            run_interaction(uri=args.uri, audio_bytes=audio_bytes,
                            user_id=args.user_id, emit=emit)
        )
    except (ConnectionRefusedError, OSError) as exc:
        emit(f"[connect] FAILED: could not reach {args.uri}: {exc}")
        emit("is the server running? (uvicorn api.app:app --port 8765)")
        _write_evidence(log, stem="manual_stream_test_FAILED")
        return 1

    if error_code is not None:
        _write_evidence(log, stem="manual_stream_test_FAILED")
        return 1

    if tts_audio and not args.no_play:
        try:
            _play_pcm16_16k(tts_audio, emit)
        except Exception as exc:  # noqa: BLE001 - best-effort playback, not the point of the test
            emit(f"[audio_output] FAILED (non-fatal): {exc}")

    emit("")
    emit("--- DEL-03 decision trace (via direct db access, see this script's docstring) ---")
    if args.no_trace_lookup:
        emit("[trace] skipped (--no-trace-lookup)")
    else:
        settings = get_settings()
        try:
            from storage.sqlite_store import SQLiteStore

            store = SQLiteStore(settings.db_path)
            trace_record = _fetch_decision_trace_by_session(
                store, args.user_id, session_id)
        except Exception as exc:  # noqa: BLE001 - reporting a lookup failure is the point here
            emit(f"[trace] could not read {settings.db_path!r}: {exc}")
            trace_record = "lookup_failed"

        if trace_record == "lookup_failed":
            pass
        elif trace_record is None:
            emit(
                f"[trace] no decision_trace row found for session_id={session_id} in "
                f"{settings.db_path!r} -- is this script running on the same machine as the server?"
            )
        else:
            for line in _render_trace_lines(trace_record):
                emit(line)

            emit("")
            emit("--- pipeline breakdown, by node (pipeline/graph.py) ---")
            for line in _render_pipeline_breakdown(trace_record):
                emit(line)

    evidence_path = _write_evidence(log, stem="manual_stream_test")
    emit(f"\n[evidence] full run transcript written to {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
