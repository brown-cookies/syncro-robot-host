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
    def __init__(self, value=None, rate=16_000):
        self.value = np.asarray(value if value is not None else [0.1, 0.2], dtype=np.float32)
        self.rate = rate
        self.calls = 0
    def capture(self):
        self.calls += 1
        return self.value, self.rate

class FakeSTT:
    def __init__(self, value="hello"):
        self.value = value
        self.calls = []
    def transcribe(self, audio, sample_rate):
        self.calls.append((audio, sample_rate))
        return self.value

class FakeLLM:
    def __init__(self, value="hi there"):
        self.value = value
        self.calls = []
    def generate(self, prompt):
        self.calls.append(prompt)
        return self.value

class FakeTTS:
    def __init__(self, value=None, rate=22_050):
        self.value = np.asarray(value if value is not None else [0.3, 0.4], dtype=np.float32)
        self.rate = rate
        self.calls = []
    def synthesize(self, text):
        self.calls.append(text)
        return self.value, self.rate

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


def test_success_has_all_stages():
    output = FakeOutput()
    stt = FakeSTT()
    llm = FakeLLM()
    tts = FakeTTS()
    result, audio, rate = make_pipeline(stt=stt, llm=llm, tts=tts, audio_output=output).run_once()
    assert result.transcript == "hello"
    assert result.response_text == "hi there"
    assert list(result.stage_durations_s) == ["audio_capture", "stt", "llm", "tts", "audio_output"]
    assert all(value >= 0 for value in result.stage_durations_s.values())
    assert np.array_equal(output.calls[0][0], audio)
    assert output.calls[0][1] == rate == 22_050

@pytest.mark.parametrize(
    ("stage", "error_type"),
    [
        ("audio_capture", AudioCaptureError),
        ("stt", STTAdapterError),
        ("llm", LLMAdapterError),
        ("tts", TTSAdapterError),
        ("audio_output", AudioPlaybackError),
    ],
)
def test_inv6_failure_stops_pipeline(stage, error_type):
    error = error_type("boom")

    class FailingTarget:
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

    deps = {
        "audio_input": FakeInput(),
        "stt": FakeSTT(),
        "llm": FakeLLM(),
        "tts": FakeTTS(),
        "audio_output": FakeOutput(),
    }
    target_name = "audio_input" if stage == "audio_capture" else stage
    deps[target_name] = FailingTarget()

    with pytest.raises(PipelineStageError) as exc:
        make_pipeline(**deps).run_once()

    assert exc.value.stage == stage
    assert exc.value.cause is error


def test_unexpected_stage_error_is_wrapped_and_stops_pipeline():
    boom = RuntimeError("unexpected boom")

    class FailingSTT(FakeSTT):
        def transcribe(self, *args, **kwargs):
            raise boom

    with pytest.raises(PipelineStageError) as exc:
        make_pipeline(stt=FailingSTT()).run_once()

    assert exc.value.stage == "stt"
    assert exc.value.cause is boom


def test_keyboard_interrupt_at_stage_boundary_is_wrapped():
    class InterruptingInput:
        def capture(self):
            raise KeyboardInterrupt()

    with pytest.raises(PipelineStageError) as exc:
        make_pipeline(audio_input=InterruptingInput()).run_once()

    assert exc.value.stage == "audio_capture"
    assert isinstance(exc.value.cause, KeyboardInterrupt)


def test_empty_transcript_stops_before_llm():
    llm = FakeLLM()
    with pytest.raises(PipelineStageError) as exc:
        make_pipeline(stt=FakeSTT(""), llm=llm).run_once()
    assert exc.value.stage == "stt"
    assert llm.calls == []


def test_empty_llm_response_stops_before_tts():
    tts = FakeTTS()
    with pytest.raises(PipelineStageError) as exc:
        make_pipeline(llm=FakeLLM(""), tts=tts).run_once()
    assert exc.value.stage == "llm"
    assert tts.calls == []
