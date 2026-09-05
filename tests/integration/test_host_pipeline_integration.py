from __future__ import annotations

import io
import sys
import types
import wave

import numpy as np

from adapters.llm import OllamaLLMAdapter
from adapters.stt import WhisperSTTAdapter
from adapters.tts import PiperTTSAdapter
from audio.capture import MicrophoneAudioInput
from audio.playback import SpeakerAudioOutput
from config.settings import Settings
from pipeline import HostPipeline


def make_wav_bytes() -> bytes:
    """Build deterministic WAV bytes for integration testing."""
    samples = np.array([0, 1000, -1000, 2000], dtype=np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def install_fake_runtime(monkeypatch):
    """Install the controlled fake runtime dependencies used by the integration test."""
    class FakeWhisperModel:
        def __init__(self, model_size, device, compute_type):
            """Initialize the FakeWhisperModel and establish its runtime state."""
            assert (model_size, device, compute_type) == ("small", "cpu", "int8")

        def transcribe(self, audio, language):
            """Transcribe the supplied audio using the configured speech-to-text backend."""
            assert language == "en"
            assert audio.dtype == np.float32
            return [types.SimpleNamespace(text=" hello integration ")], object()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    class FakeVoice:
        @classmethod
        def load(cls, path):
            """Load the configured test artifact or runtime resource."""
            assert path == "./models/test"
            return cls()

        def synthesize_wav(self, text, wav_file):
            """Build deterministic synthesized WAV output for the integration test."""
            assert text == "hello from ollama"
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(np.array([0, 1000, -1000, 2000], dtype=np.int16).tobytes())

    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=FakeVoice))

    class FakeResponse:
        text = '{"response":"hello from ollama"}'

        def raise_for_status(self):
            """Provide the fake HTTP status-check behavior used by the test."""
            return None

        def json(self):
            """Return the fake JSON payload used by the test."""
            return {"response": "hello from ollama"}

    monkeypatch.setattr(
        "adapters.llm.ollama_adapter.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    output = {}

    class FakeSD:
        def rec(self, frames, samplerate, channels, dtype, device):
            """Provide the fake audio-recording behavior used by the test."""
            assert frames == 16_000
            assert samplerate == 16_000
            assert channels == 1
            assert dtype == "float32"
            output["captured"] = True
            return np.ones((frames, channels), dtype=np.float32)

        def play(self, audio, samplerate, device):
            """Play supplied audio through the configured output device."""
            output["played_audio"] = audio
            output["played_rate"] = samplerate
            output["played"] = True

        def wait(self):
            """Provide the fake blocking behavior used by the audio test."""
            output["waited"] = True

    monkeypatch.setitem(sys.modules, "sounddevice", FakeSD())
    return output


def test_host_pipeline_concrete_components_work_together(monkeypatch):
    """Verify that host pipeline concrete components work together."""
    output = install_fake_runtime(monkeypatch)
    settings = Settings(audio_capture_seconds=1.0, piper_model_path="./models/test")

    pipeline = HostPipeline(
        audio_input=MicrophoneAudioInput(settings),
        stt=WhisperSTTAdapter(settings),
        llm=OllamaLLMAdapter(settings),
        tts=PiperTTSAdapter(settings),
        audio_output=SpeakerAudioOutput(settings),
    )

    result, synthesized, rate = pipeline.run_once()

    assert output["captured"] is True
    assert output["played"] is True
    assert output["waited"] is True
    assert result.transcript == "hello integration"
    assert result.response_text == "hello from ollama"
    assert synthesized.dtype == np.float32
    assert rate == 16_000
    assert output["played_rate"] == 16_000
    assert np.array_equal(output["played_audio"], synthesized)
    assert set(result.stage_durations_s) == {
        "audio_capture",
        "stt",
        "llm",
        "tts",
        "audio_output",
    }
