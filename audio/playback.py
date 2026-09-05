"""Host-side speaker playback for WP-102."""

from __future__ import annotations

import numpy as np

from config.settings import Settings


class AudioPlaybackError(RuntimeError):
    """Raised when host audio output is unavailable or playback fails (ERR-5)."""


class SpeakerAudioOutput:
    """Concrete host speaker implementation using sounddevice."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the SpeakerAudioOutput and establish its runtime state."""
        self._settings = settings

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play supplied audio through the configured output device."""
        try:
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover - dependency boundary
            raise AudioPlaybackError(
                "sounddevice is not installed. Install it with `pip install sounddevice`."
            ) from exc

        device = self._settings.audio_output_device or None
        try:
            sd.play(audio, samplerate=sample_rate, device=device)
            sd.wait()
        except Exception as exc:  # noqa: BLE001 - dependency boundary
            raise AudioPlaybackError(
                f"Host audio playback failed (device={device!r}, sample_rate={sample_rate}): {exc}"
            ) from exc

