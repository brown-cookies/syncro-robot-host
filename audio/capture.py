"""Host-side microphone capture for WP-102."""

from __future__ import annotations

import numpy as np

from config.settings import Settings


class AudioCaptureError(RuntimeError):
    """Raised when the host microphone cannot provide usable audio (ERR-1)."""


class MicrophoneAudioInput:
    """Concrete host microphone implementation using sounddevice."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def capture(self) -> tuple[np.ndarray, int]:
        try:
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover - dependency boundary
            raise AudioCaptureError(
                "sounddevice is not installed. Install it with `pip install sounddevice`."
            ) from exc

        sample_rate = self._settings.audio_sample_rate_hz
        channels = self._settings.audio_channels
        duration_s = self._settings.audio_capture_seconds
        device = self._settings.audio_input_device or None

        try:
            recording = sd.rec(
                int(duration_s * sample_rate),
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                device=device,
            )
            sd.wait()
        except Exception as exc:  # noqa: BLE001 - dependency boundary
            raise AudioCaptureError(
                f"USB microphone capture failed (device={device!r}, sample_rate={sample_rate}): {exc}"
            ) from exc

        audio = recording.reshape(-1) if channels == 1 else recording
        if not np.any(audio):
            raise AudioCaptureError(
                "Captured audio is all silence -- check the USB microphone is connected and selected."
            )
        return audio, sample_rate

