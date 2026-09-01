from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from adapters.stt.whisper_adapter import STTAdapterError, WhisperSTTAdapter


def install_fake_whisper(monkeypatch, *, segments=None, init_error=None, transcribe_error=None):
    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            self.args = (model_size, device, compute_type)
            if init_error:
                raise init_error

        def transcribe(self, audio, language):
            assert language == "en"
            if transcribe_error:
                raise transcribe_error
            return segments or [], object()

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    return FakeWhisperModel


def test_stt_initialization_uses_settings(monkeypatch, test_settings):
    fake_model = install_fake_whisper(monkeypatch)
    adapter = WhisperSTTAdapter(settings=test_settings)
    assert isinstance(adapter._model, fake_model)
    assert adapter._model.args == ("small", "cpu", "int8")


def test_stt_joins_segments(monkeypatch, test_settings, sample_audio):
    install_fake_whisper(monkeypatch, segments=[types.SimpleNamespace(text=" Hello "), types.SimpleNamespace(text=" world ")])
    assert WhisperSTTAdapter(settings=test_settings).transcribe(sample_audio, 16_000) == "Hello world"


def test_stt_rejects_wrong_dtype(monkeypatch, test_settings):
    install_fake_whisper(monkeypatch)
    with pytest.raises(STTAdapterError, match="Expected float32 PCM"):
        WhisperSTTAdapter(settings=test_settings).transcribe(np.array([1], dtype=np.int16), 16_000)


def test_stt_rejects_wrong_sample_rate(monkeypatch, test_settings, sample_audio):
    install_fake_whisper(monkeypatch)
    with pytest.raises(STTAdapterError, match="Expected 16000 Hz"):
        WhisperSTTAdapter(settings=test_settings).transcribe(sample_audio, 8_000)


def test_stt_wraps_transcription_failure(monkeypatch, test_settings, sample_audio):
    install_fake_whisper(monkeypatch, transcribe_error=RuntimeError("decoder failed"))
    with pytest.raises(STTAdapterError, match="Transcription failed") as exc:
        WhisperSTTAdapter(settings=test_settings).transcribe(sample_audio, 16_000)
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_stt_wraps_initialization_failure(monkeypatch, test_settings):
    install_fake_whisper(monkeypatch, init_error=RuntimeError("model unavailable"))
    with pytest.raises(STTAdapterError, match="failed to initialize"):
        WhisperSTTAdapter(settings=test_settings)
