"""Protocol contracts for host-side audio I/O."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class AudioInput(Protocol):
    """Source of host-captured PCM audio."""

    def capture(self) -> tuple[np.ndarray, int]:
        """Capture audio and return it in the format required by the host pipeline."""
        ...


class AudioOutput(Protocol):
    """Sink for host-produced PCM audio."""

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play supplied audio through the configured output device."""
        ...
