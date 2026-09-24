"""Typed application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    """Read and validate an integer environment setting."""
    raw = os.getenv(name)
    try:
        return default if raw is None or raw == "" else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _float_env(name: str, default: float) -> float:
    """Read and validate a floating-point environment setting."""
    raw = os.getenv(name)
    try:
        return default if raw is None or raw == "" else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    """Read and validate a boolean environment setting."""
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
    intent_confidence_threshold: float = 0.60

    # F6/D5 — the intent classifier and reasoning LLM are two sequential
    # Ollama calls per turn. They used to share one `ollama_timeout_s`, which
    # only guaranteed each call individually stayed under the session budget
    # — not their sum. These three are sized so
    # intent_timeout_s + reasoning_timeout_s + non_llm_timeout_margin_s stays
    # under session_timeout_seconds; see __post_init__.
    intent_timeout_s: float = 5.0
    reasoning_timeout_s: float = 6.0
    non_llm_timeout_margin_s: float = 10.0
    intent_num_predict: int = 40
    ollama_keep_alive: str = "10m"

    # One-time cold-load budget for the composition-root warm-up call, kept
    # deliberately separate from intent_timeout_s/reasoning_timeout_s: those
    # two are meant to bound per-turn *inference* latency under D5's
    # invariant, not the multi-second-to-tens-of-seconds cost of Ollama
    # loading model weights off disk on the very first call of a process.
    llm_warmup_timeout_s: float = 120.0

    # S1 — bounded queue size between the (future) async transport and the
    # single InteractionWorker thread. A caller that fills this queue gets
    # WorkerQueueFullError immediately rather than blocking the event loop;
    # this bound is how many interactions may be backlogged before that
    # happens. Small on purpose: a deep queue just delays the same overload
    # signal, it doesn't absorb it (Ollama's two sequential calls per turn
    # are the actual bottleneck, per F6).
    interaction_queue_maxsize: int = 8

    # STT
    stt_model_size: str = "small"
    stt_compute_type: str = "int8"
    stt_device: str = "cpu"

    # TTS
    piper_model_path: str = "./models/en_US-lessac-medium"
    # Scope-freeze Item 2: synthesis longer than this triggers the host half of
    # the fallback channel (text-only response, degradation_reason=tts_timeout).
    tts_timeout_s: float = 2.0

    # Task ingress (SPEC 6.1a / NFR-14): per-connector bearer tokens, as
    # comma-separated "source:token" pairs. Empty means every ingest call is
    # rejected (fail closed). Tokens must be at least 16 characters.
    ingest_source_tokens: str = ""

    # Audio
    audio_sample_rate_hz: int = 16000
    audio_channels: int = 1
    audio_capture_seconds: float = 5.0
    audio_input_device: str = ""
    audio_output_device: str = ""

    # openSMILE / affect
    opensmile_executable: str = "openSMILE"
    affect_detector_backend: str = "development"
    affect_classifier_path: str = "./models/affect/affect_svc_v1.joblib"

    # Policy
    adaptive_lead_time_enabled: bool = True
    lead_time_default: int = 15
    lead_time_min: int = 5
    lead_time_max: int = 60
    alpha: float = 0.3
    deadline_proximity_hours: int = 2
    context_top_k: int = 5
    grace_window_minutes: int = 15
    session_timeout_seconds: int = 30
    reminder_response_window_minutes: int = 10
    delivery_failed_queue_bound: int = 20

    # Logging
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Enforce the D5 sum-based timeout invariant this dataclass can't express per-field."""
        budget = (
            self.intent_timeout_s
            + self.reasoning_timeout_s
            + self.non_llm_timeout_margin_s
        )
        if budget >= self.session_timeout_seconds:
            raise ValueError(
                "D5 invariant violated: intent_timeout_s + reasoning_timeout_s + "
                f"non_llm_timeout_margin_s totals {budget}s, which is not under "
                f"session_timeout_seconds ({self.session_timeout_seconds}s). "
                "The two sequential Ollama calls could outlast the session "
                "budget even though each individually looks fine."
            )

    @classmethod
    def from_env(cls) -> "Settings":
        """Build application settings from the current environment."""
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
            intent_confidence_threshold=_float_env(
                "INTENT_CONFIDENCE_THRESHOLD", defaults.intent_confidence_threshold
            ),
            intent_timeout_s=_float_env(
                "INTENT_TIMEOUT_S", defaults.intent_timeout_s
            ),
            reasoning_timeout_s=_float_env(
                "REASONING_TIMEOUT_S", defaults.reasoning_timeout_s
            ),
            non_llm_timeout_margin_s=_float_env(
                "NON_LLM_TIMEOUT_MARGIN_S", defaults.non_llm_timeout_margin_s
            ),
            intent_num_predict=_int_env(
                "INTENT_NUM_PREDICT", defaults.intent_num_predict
            ),
            ollama_keep_alive=os.getenv(
                "OLLAMA_KEEP_ALIVE", defaults.ollama_keep_alive
            ),
            llm_warmup_timeout_s=_float_env(
                "LLM_WARMUP_TIMEOUT_S", defaults.llm_warmup_timeout_s
            ),
            interaction_queue_maxsize=_int_env(
                "INTERACTION_QUEUE_MAXSIZE", defaults.interaction_queue_maxsize
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
            tts_timeout_s=_float_env("TTS_TIMEOUT_S", defaults.tts_timeout_s),
            ingest_source_tokens=os.getenv(
                "INGEST_SOURCE_TOKENS", defaults.ingest_source_tokens
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
            affect_detector_backend=os.getenv(
                "AFFECT_DETECTOR_BACKEND", defaults.affect_detector_backend
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
            context_top_k=_int_env(
                "CONTEXT_TOP_K", defaults.context_top_k
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
    """Return the immutable settings snapshot used by the running process."""
    return Settings.from_env()

