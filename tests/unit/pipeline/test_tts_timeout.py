"""Scope-freeze Item 2: TTS timeout -> host half of the fallback channel.

A forced timeout (a stub TTS that blocks until released) makes the behavior
deterministic without a slow real engine: the runner must finish the
interaction, persist a full trace with degradation_reason="tts_timeout",
return empty audio plus the text, and print the fallback line to the console.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pytest

from adapters.tts.piper_adapter import TTSAdapterError
from audio.resample import to_pcm16_16k
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext


def _pending_trace():
    return {
        "trace_id": uuid4(), "session_id": "s1", "user_id": "u1",
        "timestamp": datetime.now(timezone.utc), "intent": "snooze_reminder",
        "intent_confidence": 0.9, "retrieved_context_ids": [],
        "affect_level": "High", "deadline_proximity": "imminent",
        "policy_rule": "R5", "action_taken": "deliver", "lead_time_min": 15.0,
        "reminder_outcome": "pending", "degradation_reason": None,
        "network_event": None,
    }


class _Graph:
    def invoke(self, state):
        return {
            "response_payload": {
                "type": "response", "session_id": state["session_id"],
                "tts_text": "Let's focus on the most important item first.",
                "state_tag": "speaking", "policy_rule": "R5", "lead_time_min": 15.0,
            },
            "pending_trace": _pending_trace(),
            "stage_timings_s": {"stt": 0.01},
        }


class _Store:
    def __init__(self):
        self.saved, self.saved_degraded = [], []

    def ensure_user(self, user_id):
        pass

    def save_decision_trace(self, record):
        self.saved.append(record)

    def save_degraded_trace(self, record):
        self.saved_degraded.append(record)


class _BlockingTTS:
    """Blocks until released, so the timeout is forced deterministically."""

    def __init__(self):
        self.release = threading.Event()

    def synthesize(self, text):
        self.release.wait(timeout=5)
        return np.zeros(2_205, dtype=np.float32), 22_050


class _FastTTS:
    def synthesize(self, text):
        return np.zeros(2_205, dtype=np.float32), 22_050


class _FailingTTS:
    def synthesize(self, text):
        raise TTSAdapterError("Piper synthesis failed: boom")


def _session():
    return SessionContext(session_id="s1", user_id="u1", started_monotonic=0.0)


def _runner(tts, store, console, timeout=0.05):
    return InteractionRunner(
        graph=_Graph(), store=store, tts=tts, resampler=to_pcm16_16k,
        tts_timeout_s=timeout, console=console.append,
    )


def _run(runner):
    return runner.run(
        session=_session(), audio=np.zeros(160, dtype=np.float32), sample_rate=16_000
    )


def test_forced_tts_timeout_degrades_traces_and_prints_fallback_line():
    tts, store, console = _BlockingTTS(), _Store(), []
    try:
        result = _run(_runner(tts, store, console))
    finally:
        tts.release.set()

    assert result.degradation_reason == "tts_timeout"
    assert result.tts_audio.size == 0
    # The edge still receives the text to fall back on.
    assert result.response_payload["tts_text"].startswith("Let's focus")
    # Full trace (policy result kept), marked degraded; not a degraded-only row.
    assert len(store.saved) == 1 and store.saved_degraded == []
    assert store.saved[0]["degradation_reason"] == "tts_timeout"
    assert store.saved[0]["policy_rule"] == "R5"
    assert any("TTS timed out" in line and "fallback channel activated" in line
               for line in console)


def test_tts_within_timeout_is_not_degraded_and_console_is_silent():
    store, console = _Store(), []
    result = _run(_runner(_FastTTS(), store, console, timeout=2.0))

    assert result.degradation_reason is None
    assert result.tts_audio.size > 0
    assert store.saved[0]["degradation_reason"] is None
    assert console == []


def test_tts_adapter_error_still_maps_to_interaction_error():
    store, console = _Store(), []
    with pytest.raises(InteractionError) as exc_info:
        _run(_runner(_FailingTTS(), store, console, timeout=2.0))

    assert exc_info.value.stage == "tts"
    assert store.saved == []          # no normal trace for a failed interaction
    assert console == []


def test_tts_timeout_setting_defaults_to_two_seconds_and_reads_env(monkeypatch):
    from config.settings import Settings

    monkeypatch.delenv("TTS_TIMEOUT_S", raising=False)
    assert Settings.from_env().tts_timeout_s == 2.0
    monkeypatch.setenv("TTS_TIMEOUT_S", "1.5")
    assert Settings.from_env().tts_timeout_s == 1.5
