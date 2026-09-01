from __future__ import annotations

import numpy as np
import pytest

from adapters.llm import LLMAdapterError
from adapters.stt import STTAdapterError
from adapters.tts import TTSAdapterError
from audio.capture import AudioCaptureError
from audio.playback import AudioPlaybackError
from pipeline import HostPipeline, PipelineStageError


class FakeInput:
    def __init__(self, audio=None, sample_rate=16000):
        self.audio = np.asarray(audio if audio is not None else [0.1, 0.2], dtype=np.float32)
        self.sample_rate = sample_rate

    def capture(self):
        return self.audio, self.sample_rate


class FakeSTT:
    def __init__(self, value="hello"):
        self.value = value

    def transcribe(self, audio, sample_rate):
        return self.value


class FakeLLM:
    def __init__(self, value="hi there"):
        self.value = value

    def generate(self, prompt):
        return self.value


class FakeTTS:
    def __init__(self, audio=None, sample_rate=22050):
        self.audio = np.asarray(audio if audio is not None else [0.3, 0.4], dtype=np.float32)
        self.sample_rate = sample_rate

    def synthesize(self, text):
        return self.audio, self.sample_rate


class FakeOutput:
    def __init__(self):
        self.calls = []

    def play(self, audio, sample_rate):
        self.calls.append((audio, sample_rate))


def make_pipeline(**kwargs):
    return HostPipeline(
        audio_input=kwargs.get("audio_input", FakeInput()),
        stt=kwargs.get("stt", FakeSTT()),
        llm=kwargs.get("llm", FakeLLM()),
        tts=kwargs.get("tts", FakeTTS()),
        audio_output=kwargs.get("audio_output", FakeOutput()),
    )


def test_success_path_has_all_wp102_stages():
    output = FakeOutput()
    pipeline = make_pipeline(audio_output=output)

    result, audio, rate = pipeline.run_once()

    assert result.transcript == "hello"
    assert result.response_text == "hi there"
    assert list(result.stage_durations_s) == [
        "audio_capture", "stt", "llm", "tts", "audio_output"
    ]
    assert audio.dtype == np.float32
    assert rate == 22050
    assert len(output.calls) == 1


@pytest.mark.parametrize(
    ("dependency", "error", "stage"),
    [
        ("audio_input", AudioCaptureError("boom"), "audio_capture"),
        ("stt", STTAdapterError("boom"), "stt"),
        ("llm", LLMAdapterError("boom"), "llm"),
        ("tts", TTSAdapterError("boom"), "tts"),
        ("audio_output", AudioPlaybackError("boom"), "audio_output"),
    ],
)
def test_any_required_stage_failure_fails_pipeline(dependency, error, stage):
    class Failing:
        def capture(self):
            raise error
        def transcribe(self, *args, **kwargs):
            raise error
        def generate(self, *args, **kwargs):
            raise error
        def synthesize(self, *args, **kwargs):
            raise error
        def play(self, *args, **kwargs):
            raise error

    deps = {dependency: Failing()}
    pipeline = make_pipeline(**deps)

    with pytest.raises(PipelineStageError) as exc_info:
        pipeline.run_once()

    assert exc_info.value.stage == stage
    assert exc_info.value.cause is error


def test_empty_transcript_stops_before_llm():
    llm = FakeLLM()
    pipeline = make_pipeline(stt=FakeSTT(""), llm=llm)

    with pytest.raises(PipelineStageError) as exc_info:
        pipeline.run_once()

    assert exc_info.value.stage == "stt"


def test_empty_llm_response_stops_before_tts():
    pipeline = make_pipeline(llm=FakeLLM(""))

    with pytest.raises(PipelineStageError) as exc_info:
        pipeline.run_once()

    assert exc_info.value.stage == "llm"
