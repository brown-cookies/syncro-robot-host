"""Typed application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return default if raw is None or raw == "" else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return default if raw is None or raw == "" else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be boolean, got {raw!r}")


@dataclass(frozen=True, slots=True)
class Settings:
    # Host
    host_address: str = "0.0.0.0"
    ws_port: int = 8765
    db_path: str = "./syncro.db"

    # LLM
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "llama3.1:8b-instruct-q4_K_M"
    ollama_num_ctx: int = 2048
    ollama_timeout_s: float = 60.0

    # STT
    stt_model_size: str = "small"
    stt_compute_type: str = "int8"
    stt_device: str = "cpu"

    # TTS
    piper_model_path: str = "./models/en_US-lessac-medium"

    # Audio
    audio_sample_rate_hz: int = 16000
    audio_channels: int = 1
    audio_capture_seconds: float = 5.0
    audio_input_device: str = ""
    audio_output_device: str = ""

    # openSMILE / affect
    opensmile_executable: str = "openSMILE"
    affect_classifier_path: str = "./models/affect_classifier.pkl"

    # Policy
    adaptive_lead_time_enabled: bool = True
    lead_time_default: int = 15
    lead_time_min: int = 5
    lead_time_max: int = 60
    alpha: float = 0.3
    deadline_proximity_hours: int = 2
    grace_window_minutes: int = 15
    session_timeout_seconds: int = 30
    reminder_response_window_minutes: int = 10
    delivery_failed_queue_bound: int = 20

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()

        return cls(
            # Host
            host_address=os.getenv("HOST_ADDRESS", defaults.host_address),
            ws_port=_int_env("WS_PORT", defaults.ws_port),
            db_path=os.getenv("DB_PATH", defaults.db_path),

            # LLM
            ollama_url=os.getenv("OLLAMA_URL", defaults.ollama_url),
            llm_model=os.getenv("LLM_MODEL", defaults.llm_model),
            ollama_num_ctx=_int_env("OLLAMA_NUM_CTX", defaults.ollama_num_ctx),
            ollama_timeout_s=_float_env(
                "OLLAMA_TIMEOUT_S", defaults.ollama_timeout_s
            ),

            # STT
            stt_model_size=os.getenv(
                "STT_MODEL_SIZE", defaults.stt_model_size
            ),
            stt_compute_type=os.getenv(
                "STT_COMPUTE_TYPE", defaults.stt_compute_type
            ),
            stt_device=os.getenv("STT_DEVICE", defaults.stt_device),

            # TTS
            piper_model_path=os.getenv(
                "PIPER_MODEL_PATH", defaults.piper_model_path
            ),
            # Audio
            audio_sample_rate_hz=_int_env(
                "AUDIO_SAMPLE_RATE_HZ", defaults.audio_sample_rate_hz
            ),
            audio_channels=_int_env(
                "AUDIO_CHANNELS", defaults.audio_channels
            ),
            audio_capture_seconds=_float_env(
                "AUDIO_CAPTURE_SECONDS", defaults.audio_capture_seconds
            ),
            audio_input_device=os.getenv(
                "AUDIO_INPUT_DEVICE", defaults.audio_input_device
            ),
            audio_output_device=os.getenv(
                "AUDIO_OUTPUT_DEVICE", defaults.audio_output_device
            ),

            # openSMILE / affect
            opensmile_executable=os.getenv(
                "OPENSMILE_EXECUTABLE", defaults.opensmile_executable
            ),
            affect_classifier_path=os.getenv(
                "AFFECT_CLASSIFIER_PATH",
                defaults.affect_classifier_path,
            ),

            # Policy
            adaptive_lead_time_enabled=_bool_env(
                "ADAPTIVE_LEAD_TIME_ENABLED",
                defaults.adaptive_lead_time_enabled,
            ),
            lead_time_default=_int_env(
                "LEAD_TIME_DEFAULT", defaults.lead_time_default
            ),
            lead_time_min=_int_env(
                "LEAD_TIME_MIN", defaults.lead_time_min
            ),
            lead_time_max=_int_env(
                "LEAD_TIME_MAX", defaults.lead_time_max
            ),
            alpha=_float_env("ALPHA", defaults.alpha),
            deadline_proximity_hours=_int_env(
                "DEADLINE_PROXIMITY_HOURS",
                defaults.deadline_proximity_hours,
            ),
            grace_window_minutes=_int_env(
                "GRACE_WINDOW_MINUTES",
                defaults.grace_window_minutes,
            ),
            session_timeout_seconds=_int_env(
                "SESSION_TIMEOUT_SECONDS",
                defaults.session_timeout_seconds,
            ),
            reminder_response_window_minutes=_int_env(
                "REMINDER_RESPONSE_WINDOW_MINUTES",
                defaults.reminder_response_window_minutes,
            ),
            delivery_failed_queue_bound=_int_env(
                "DELIVERY_FAILED_QUEUE_BOUND",
                defaults.delivery_failed_queue_bound,
            ),

            # Logging
            log_level=os.getenv("LOG_LEVEL", defaults.log_level),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable settings snapshot for the running process."""
    return Settings.from_env()

