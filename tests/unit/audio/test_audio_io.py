from __future__ import annotations

import sys

import numpy as np
import pytest

from audio.capture import AudioCaptureError, MicrophoneAudioInput
from audio.playback import AudioPlaybackError, SpeakerAudioOutput


def test_capture_returns_pcm(monkeypatch, test_settings):
    """Verify that capture returns pcm."""
    calls = {}

    class FakeSD:
        def rec(self, frames, samplerate, channels, dtype, device):
            """Provide the fake audio-recording behavior used by the test."""
            calls.update(frames=frames, samplerate=samplerate, channels=channels, dtype=dtype, device=device)
            return np.ones((frames, channels), dtype=np.float32)
        def wait(self):
            """Provide the fake blocking behavior used by the audio test."""
            calls["waited"] = True

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
    audio, rate = MicrophoneAudioInput(test_settings).capture()
    assert audio.dtype == np.float32
    assert audio.shape == (16_000,)
    assert rate == 16_000
    assert calls["device"] is None
    assert calls["waited"] is True


def test_capture_wraps_failure(monkeypatch, test_settings):
    """Verify that capture wraps failure."""
    class FakeSD:
        def rec(self, **kwargs):
            """Provide the fake audio-recording behavior used by the test."""
            raise RuntimeError("device unavailable")
        def wait(self):
            """Provide the fake blocking behavior used by the audio test."""
            pass
    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
    with pytest.raises(AudioCaptureError, match="USB microphone capture failed"):
        MicrophoneAudioInput(test_settings).capture()


def test_capture_rejects_silence(monkeypatch, test_settings):
    """Verify that capture rejects silence."""
    class FakeSD:
        def rec(self, frames, **kwargs):
            """Provide the fake audio-recording behavior used by the test."""
            return np.zeros((frames, 1), dtype=np.float32)
        def wait(self):
            """Provide the fake blocking behavior used by the audio test."""
            pass
    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
    with pytest.raises(AudioCaptureError, match="all silence"):
        MicrophoneAudioInput(test_settings).capture()


def test_playback_uses_sounddevice(monkeypatch, test_settings, sample_audio):
    """Verify that playback uses sounddevice."""
    calls = {}

    class FakeSD:
        def play(self, audio, samplerate, device):
            """Play supplied audio through the configured output device."""
            calls.update(audio=audio, samplerate=samplerate, device=device)
        def wait(self):
            """Provide the fake blocking behavior used by the audio test."""
            calls["waited"] = True

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
    SpeakerAudioOutput(test_settings).play(sample_audio, 16_000)
    assert np.array_equal(calls["audio"], sample_audio)
    assert calls["samplerate"] == 16_000
    assert calls["device"] is None
    assert calls["waited"] is True


def test_playback_wraps_failure(monkeypatch, test_settings, sample_audio):
    """Verify that playback wraps failure."""
    class FakeSD:
        def play(self, *args, **kwargs):
            """Play supplied audio through the configured output device."""
            raise RuntimeError("output unavailable")
        def wait(self):
            """Provide the fake blocking behavior used by the audio test."""
            pass
    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
    with pytest.raises(AudioPlaybackError, match="Host audio playback failed"):
        SpeakerAudioOutput(test_settings).play(sample_audio, 16_000)
