"""Technology-neutral processing contracts used by the host pipeline."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class STT(Protocol):
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        """Transcribe the supplied audio using the configured speech-to-text backend."""
        ...
class LLM(Protocol):
    def generate(self, prompt: str) -> str:
        """Generate an LLM response from the supplied conversation state and context."""
        ...
class TTS(Protocol):
    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize speech from the supplied text using the configured text-to-speech backend."""
        ...
class IntentClassifier(Protocol):
    def classify(self, transcript: str) -> tuple[str, float, dict[str, object]]:
        """Classify the supplied input using the configured classifier."""
        ...