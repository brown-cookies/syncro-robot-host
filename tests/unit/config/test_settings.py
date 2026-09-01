from __future__ import annotations

import pytest

from config.settings import Settings


def test_settings_defaults_are_instance_values() -> None:
    settings = Settings()
    assert settings.audio_sample_rate_hz == 16_000
    assert settings.audio_capture_seconds == 5.0
    assert settings.ws_port == 8765


def test_settings_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("AUDIO_SAMPLE_RATE_HZ", "22050")
    monkeypatch.setenv("AUDIO_CAPTURE_SECONDS", "2.5")
    monkeypatch.setenv("WS_PORT", "9000")
    settings = Settings.from_env()
    assert settings.audio_sample_rate_hz == 22_050
    assert settings.audio_capture_seconds == 2.5
    assert settings.ws_port == 9000


def test_settings_rejects_invalid_integer(monkeypatch) -> None:
    monkeypatch.setenv("WS_PORT", "bad")
    with pytest.raises(ValueError, match="WS_PORT must be an integer"):
        Settings.from_env()


def test_settings_rejects_invalid_boolean(monkeypatch) -> None:
    monkeypatch.setenv("ADAPTIVE_LEAD_TIME_ENABLED", "maybe")
    with pytest.raises(ValueError, match="must be boolean"):
        Settings.from_env()
