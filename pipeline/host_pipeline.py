"""WP-102 host-only audio pipeline.

The pipeline orchestrates technology-neutral contracts only. Concrete hardware
and AI runtime implementations are assembled by the composition wiring root.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from adapters.contracts import LLM, STT, TTS
from adapters.llm import LLMAdapterError
from adapters.stt import STTAdapterError
from adapters.tts import TTSAdapterError
from audio.contracts import AudioInput, AudioOutput
from audio.capture import AudioCaptureError
from audio.playback import AudioPlaybackError


class PipelineStageError(RuntimeError):
    """Raised when a required WP-102 stage fails."""

    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(f"WP-102 pipeline failed at stage '{stage}': {cause}")
        self.stage = stage
        self.cause = cause


@dataclass(frozen=True, slots=True)
class PipelineResult:
    transcript: str
    response_text: str
    stage_durations_s: dict[str, float] = field(default_factory=dict)

    @property
    def total_duration_s(self) -> float:
        return sum(self.stage_durations_s.values())


class HostPipeline:
    """Execute audio capture → STT → LLM → TTS → host playback."""

    def __init__(
        self,
        *,
        audio_input: AudioInput,
        stt: STT,
        llm: LLM,
        tts: TTS,
        audio_output: AudioOutput,
    ) -> None:
        self._audio_input = audio_input
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._audio_output = audio_output

    def run_once(self) -> tuple[PipelineResult, np.ndarray, int]:
        durations: dict[str, float] = {}

        captured, capture_rate = self._run_stage(
            "audio_capture",
            self._audio_input.capture,
            AudioCaptureError,
            durations,
        )

        transcript = self._run_stage(
            "stt",
            lambda: self._stt.transcribe(captured, sample_rate=capture_rate),
            STTAdapterError,
            durations,
        )
        if not transcript.strip():
            self._raise_stage("stt", STTAdapterError("Transcript was empty; nothing to send to the LLM."))

        response_text = self._run_stage(
            "llm",
            lambda: self._llm.generate(transcript),
            LLMAdapterError,
            durations,
        )
        if not response_text.strip():
            self._raise_stage("llm", LLMAdapterError("LLM returned an empty response."))

        synthesized_audio, tts_rate = self._run_stage(
            "tts",
            lambda: self._tts.synthesize(response_text),
            TTSAdapterError,
            durations,
        )

        self._run_stage(
            "audio_output",
            lambda: self._audio_output.play(synthesized_audio, sample_rate=tts_rate),
            AudioPlaybackError,
            durations,
        )

        result = PipelineResult(
            transcript=transcript,
            response_text=response_text,
            stage_durations_s=durations,
        )
        return result, synthesized_audio, tts_rate

    @staticmethod
    def _raise_stage(stage: str, cause: Exception) -> None:
        raise PipelineStageError(stage, cause) from cause

    @staticmethod
    def _run_stage(stage: str, operation, expected_error: type[Exception], durations: dict[str, float]):
        start = time.monotonic()
        try:
            return operation()
        except expected_error as exc:
            raise PipelineStageError(stage, exc) from exc
        except Exception as exc:  # noqa: BLE001 - stage boundary
            raise PipelineStageError(stage, exc) from exc
        finally:
            durations[stage] = time.monotonic() - start
