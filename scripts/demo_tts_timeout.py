"""Rehearsal demo (scope-freeze Item 2): forced TTS timeout -> fallback channel.

Uses a stub TTS that hangs, a canned graph result, and a temporary real SQLite
store, so it needs no Piper, Ollama, or microphone and behaves identically on
every run. Shows the same two things the acceptance item asks for:
  CONSOLE: TTS timed out -- fallback channel activated
  TRACE:   degradation_reason = tts_timeout (row read back from the database)

Run:  python -m scripts.demo_tts_timeout
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

import numpy as np

from audio.resample import to_pcm16_16k
from pipeline.interaction import InteractionRunner, SessionContext
from storage.sqlite_store import SQLiteStore

USER_ID, SESSION_ID = "demo-user", "demo-session"


class HangingTTS:
    """Blocks until released: a deterministic stand-in for a stuck engine."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def synthesize(self, text: str):
        self.release.wait(timeout=10)
        return np.zeros(2_205, dtype=np.float32), 22_050


class CannedGraph:
    """Returns what the dialogue graph would for a High/imminent reminder (R5)."""

    def invoke(self, state):
        from datetime import datetime, timezone
        from uuid import uuid4

        return {
            "response_payload": {
                "type": "response", "session_id": state["session_id"],
                "tts_text": "Let's focus on the most important item first.",
                "state_tag": "speaking", "policy_rule": "R5", "lead_time_min": 15.0,
            },
            "pending_trace": {
                "trace_id": uuid4(), "session_id": state["session_id"],
                "user_id": state["user_id"], "timestamp": datetime.now(timezone.utc),
                "intent": "snooze_reminder", "intent_confidence": 0.9,
                "retrieved_context_ids": [], "affect_level": "High",
                "deadline_proximity": "imminent", "policy_rule": "R5",
                "action_taken": "deliver", "lead_time_min": 15.0,
                "reminder_outcome": "pending", "degradation_reason": None,
                "network_event": None,
            },
            "stage_timings_s": {},
        }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteStore(str(Path(tmp) / "demo.db"))
        tts = HangingTTS()
        runner = InteractionRunner(
            graph=CannedGraph(), store=store, tts=tts, resampler=to_pcm16_16k,
            tts_timeout_s=0.5,
        )
        try:
            result = runner.run(
                session=SessionContext(SESSION_ID, USER_ID, started_monotonic=0.0),
                audio=np.zeros(160, dtype=np.float32), sample_rate=16_000,
            )
        finally:
            tts.release.set()

        row = store.list_decision_traces(USER_ID)[-1]
        print(f"[result] degradation_reason={result.degradation_reason} "
              f"audio_samples={result.tts_audio.size} "
              f"text={result.response_payload['tts_text']!r}")
        print(f"[trace]  trace_id={row['trace_id']} policy_rule={row['policy_rule']} "
              f"degradation_reason={row['degradation_reason']}")


if __name__ == "__main__":
    main()
