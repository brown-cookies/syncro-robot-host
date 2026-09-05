from __future__ import annotations

import io
import sys
import types
import wave

import numpy as np
import pytest

from adapters.tts.piper_adapter import PiperTTSAdapter, TTSAdapterError


def wav_bytes() -> bytes:
    """Build deterministic WAV bytes for the adapter test."""
    raw = np.array([0, 1000, -1000, 2000], dtype=np.int16).tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(raw)
    return buffer.getvalue()


def install_fake_piper(monkeypatch, *, load_error=None, synth_error=None):
    """Perform the install fake piper operation required by the project."""
    data = wav_bytes()

    class FakeVoice:
        @classmethod
        def load(cls, path):
            """Load the configured test artifact or runtime resource."""
            if load_error:
                raise load_error
            return cls()

        def synthesize_wav(self, text, wav_file):
            """Build deterministic synthesized WAV output for the integration test."""
            if synth_error:
                raise synth_error
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(np.array([0, 1000, -1000, 2000], dtype=np.int16).tobytes())

    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=FakeVoice))


def test_tts_synthesizes_pcm(monkeypatch, test_settings):
    """Verify that tts synthesizes pcm."""
    install_fake_piper(monkeypatch)
    audio, rate = PiperTTSAdapter(settings=test_settings).synthesize("hello")
    assert rate == 16_000
    assert audio.dtype == np.float32
    assert audio.shape == (4,)
    assert np.max(np.abs(audio)) <= 1.0


def test_tts_rejects_empty_text(monkeypatch, test_settings):
    """Verify that tts rejects empty text."""
    install_fake_piper(monkeypatch)
    with pytest.raises(TTSAdapterError, match="empty text"):
        PiperTTSAdapter(settings=test_settings).synthesize(" ")


def test_tts_wraps_synthesis_failure(monkeypatch, test_settings):
    """Verify that tts wraps synthesis failure."""
    install_fake_piper(monkeypatch, synth_error=RuntimeError("voice crashed"))
    with pytest.raises(TTSAdapterError, match="Piper synthesis failed"):
        PiperTTSAdapter(settings=test_settings).synthesize("hello")


def test_tts_wraps_initialization_failure(monkeypatch, test_settings):
    """Verify that tts wraps initialization failure."""
    install_fake_piper(monkeypatch, load_error=RuntimeError("missing voice"))
    with pytest.raises(TTSAdapterError, match="failed to load"):
        PiperTTSAdapter(settings=test_settings)
