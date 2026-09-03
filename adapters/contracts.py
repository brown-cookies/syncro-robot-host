"""Technology-neutral processing contracts used by the host pipeline."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class STT(Protocol):
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str: ...


class LLM(Protocol):
    def generate(self, prompt: str) -> str: ...


class TTS(Protocol):
    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...


class IntentClassifier(Protocol):
    def classify(self, transcript: str) -> tuple[str, float, dict[str, object]]: ...
