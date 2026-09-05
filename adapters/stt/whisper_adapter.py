"""faster-whisper implementation of the STT adapter contract."""

from __future__ import annotations

import numpy as np

from config.settings import Settings, get_settings


class STTAdapterError(RuntimeError):
    """Raised when faster-whisper fails to initialize or transcribe."""


class WhisperSTTAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the WhisperSTTAdapter and establish its runtime state."""
        settings = settings or get_settings()
        self._sample_rate = settings.audio_sample_rate_hz
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - dependency boundary
            raise STTAdapterError(
                "faster-whisper is not installed. Run `pip install faster-whisper`."
            ) from exc

        try:
            self._model = WhisperModel(
                settings.stt_model_size,
                device=settings.stt_device,
                compute_type=settings.stt_compute_type,
            )
        except Exception as exc:  # noqa: BLE001 - dependency boundary
            raise STTAdapterError(
                f"faster-whisper failed to initialize (model={settings.stt_model_size!r}, "
                f"device={settings.stt_device!r}, compute_type={settings.stt_compute_type!r}): {exc}"
            ) from exc

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        """Transcribe the supplied audio using the configured speech-to-text backend."""
        if audio.dtype != np.float32:
            raise STTAdapterError(
                f"Expected float32 PCM, got {audio.dtype}. Convert before calling transcribe()."
            )
        if sample_rate != self._sample_rate:
            raise STTAdapterError(
                f"Expected {self._sample_rate} Hz audio, got {sample_rate} Hz."
            )
        try:
            segments, _info = self._model.transcribe(audio, language="en")
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:  # noqa: BLE001 - dependency boundary
            raise STTAdapterError(f"Transcription failed: {exc}") from exc
        return text
