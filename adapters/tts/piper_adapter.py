"""Piper implementation of the TTS adapter contract."""

from __future__ import annotations

import io
import wave

import numpy as np

from config.settings import Settings, get_settings


class TTSAdapterError(RuntimeError):
    """Raised when Piper fails to initialize or synthesize."""


class PiperTTSAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        try:
            from piper import PiperVoice
        except ImportError as exc:  # pragma: no cover - dependency boundary
            raise TTSAdapterError(
                "piper-tts is not installed. Run `pip install piper-tts`."
            ) from exc
        try:
            self._voice = PiperVoice.load(settings.piper_model_path)
        except Exception as exc:  # noqa: BLE001 - dependency boundary
            raise TTSAdapterError(
                f"Piper failed to load voice model at {settings.piper_model_path!r}: {exc}"
            ) from exc

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        if not text.strip():
            raise TTSAdapterError("Refusing to synthesize empty text.")
        try:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                self._voice.synthesize_wav(text, wav_file)
            buffer.seek(0)
            with wave.open(buffer, "rb") as wav_file:
                sample_rate = wav_file.getframerate()
                raw = wav_file.readframes(wav_file.getnframes())
        except Exception as exc:  # noqa: BLE001
            raise TTSAdapterError(f"Piper synthesis failed: {exc}") from exc

        pcm16 = np.frombuffer(raw, dtype=np.int16)
        audio = pcm16.astype(np.float32) / 32768.0
        if audio.size == 0:
            raise TTSAdapterError("Piper produced zero audio samples.")
        return audio, sample_rate
