"""Protocol contracts for host-side audio I/O."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class AudioInput(Protocol):
    """Source of host-captured PCM audio."""

    def capture(self) -> tuple[np.ndarray, int]:
        """Return (mono float32 PCM samples, sample rate)."""
        ...


class AudioOutput(Protocol):
    """Sink for host-produced PCM audio."""

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play the supplied PCM audio."""
        ...
