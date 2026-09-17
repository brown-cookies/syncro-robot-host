from __future__ import annotations

import pytest

from config.settings import Settings


def test_settings_defaults_are_instance_values() -> None:
    """Verify that settings defaults are instance values."""
    settings = Settings()
    assert settings.audio_sample_rate_hz == 16_000
    assert settings.audio_capture_seconds == 5.0
    assert settings.ws_port == 8765


def test_settings_reads_environment(monkeypatch) -> None:
    """Verify that settings reads environment."""
    monkeypatch.setenv("AUDIO_SAMPLE_RATE_HZ", "22050")
    monkeypatch.setenv("AUDIO_CAPTURE_SECONDS", "2.5")
    monkeypatch.setenv("WS_PORT", "9000")
    settings = Settings.from_env()
    assert settings.audio_sample_rate_hz == 22_050
    assert settings.audio_capture_seconds == 2.5
    assert settings.ws_port == 9000


def test_settings_rejects_invalid_integer(monkeypatch) -> None:
    """Verify that settings rejects invalid integer."""
    monkeypatch.setenv("WS_PORT", "bad")
    with pytest.raises(ValueError, match="WS_PORT must be an integer"):
        Settings.from_env()


def test_settings_rejects_invalid_boolean(monkeypatch) -> None:
    """Verify that settings rejects invalid boolean."""
    monkeypatch.setenv("ADAPTIVE_LEAD_TIME_ENABLED", "maybe")
    with pytest.raises(ValueError, match="must be boolean"):
        Settings.from_env()


def test_default_timeout_budget_satisfies_d5_invariant() -> None:
    """D5/Phase 9: the shipped defaults must leave the two sequential Ollama
    calls under the session timeout, not just each call individually."""
    settings = Settings()
    budget = (
        settings.intent_timeout_s
        + settings.reasoning_timeout_s
        + settings.non_llm_timeout_margin_s
    )
    assert budget < settings.session_timeout_seconds


def test_settings_rejects_a_timeout_budget_that_violates_d5() -> None:
    """A per-call-only-safe configuration (25s vs. a 30s session timeout)
    must still be rejected once the two calls are summed with margin --
    this is the exact F6 failure mode D5 corrects."""
    with pytest.raises(ValueError, match="D5 invariant violated"):
        Settings(
            intent_timeout_s=25.0,
            reasoning_timeout_s=25.0,
            non_llm_timeout_margin_s=0.0,
            session_timeout_seconds=30,
        )


def test_settings_reads_split_timeout_environment(monkeypatch) -> None:
    """Verify intent/reasoning timeouts, margin, num_predict, and keep_alive
    are each read from their own environment variable (D5/Phase 9)."""
    monkeypatch.setenv("INTENT_TIMEOUT_S", "4")
    monkeypatch.setenv("REASONING_TIMEOUT_S", "7")
    monkeypatch.setenv("NON_LLM_TIMEOUT_MARGIN_S", "8")
    monkeypatch.setenv("INTENT_NUM_PREDICT", "32")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "5m")
    settings = Settings.from_env()
    assert settings.intent_timeout_s == 4.0
    assert settings.reasoning_timeout_s == 7.0
    assert settings.non_llm_timeout_margin_s == 8.0
    assert settings.intent_num_predict == 32
    assert settings.ollama_keep_alive == "5m"


def test_settings_reads_interaction_queue_maxsize_environment(monkeypatch) -> None:
    """S1/Phase 12: the InteractionWorker's bounded queue size is configurable
    like every other budget in this file, and defaults sanely without one."""
    settings = Settings()
    assert settings.interaction_queue_maxsize == 8

    monkeypatch.setenv("INTERACTION_QUEUE_MAXSIZE", "3")
    settings = Settings.from_env()
    assert settings.interaction_queue_maxsize == 3
