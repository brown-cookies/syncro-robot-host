import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Host
    HOST_ADDRESS = os.getenv("HOST_ADDRESS", "0.0.0.0")
    WS_PORT = int(os.getenv("WS_PORT", 8765))
    DB_PATH = os.getenv("DB_PATH", "./syncro.db")

    # LLM
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1:8b-instruct-q4_K_M")
    OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", 2048))

    # STT
    STT_MODEL_SIZE = os.getenv("STT_MODEL_SIZE", "small")
    STT_COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8")
    # keeps Ollama's VRAM headroom untouched — WP-101 budget
    STT_DEVICE = os.getenv("STT_DEVICE", "cpu")

    # TTS
    PIPER_MODEL_PATH = os.getenv(
        "PIPER_MODEL_PATH", "./models/en_US-lessac-medium")
    TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", 16000))
    TTS_CHUNK_MS = int(os.getenv("TTS_CHUNK_MS", 100))

    # openSMILE / affect (WP-104, not wired until W1)
    OPENSMILE_EXECUTABLE = os.getenv("OPENSMILE_EXECUTABLE", "openSMILE")
    AFFECT_CLASSIFIER_PATH = os.getenv(
        "AFFECT_CLASSIFIER_PATH", "./models/affect_classifier.pkl")

    # Policy (WP-103, not wired until W1)
    ADAPTIVE_LEAD_TIME_ENABLED = os.getenv(
        "ADAPTIVE_LEAD_TIME_ENABLED", "true").lower() == "true"
    LEAD_TIME_DEFAULT = int(os.getenv("LEAD_TIME_DEFAULT", 15))
    LEAD_TIME_MIN = int(os.getenv("LEAD_TIME_MIN", 5))
    LEAD_TIME_MAX = int(os.getenv("LEAD_TIME_MAX", 60))
    ALPHA = float(os.getenv("ALPHA", 0.3))
    DEADLINE_PROXIMITY_HOURS = int(os.getenv("DEADLINE_PROXIMITY_HOURS", 2))
    GRACE_WINDOW_MINUTES = int(os.getenv("GRACE_WINDOW_MINUTES", 15))
    SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", 30))

    # OPEN ITEMS (SPEC §16) — placeholders, not confirmed values. Do not treat as decided.
    REMINDER_RESPONSE_WINDOW_MINUTES = int(
        os.getenv("REMINDER_RESPONSE_WINDOW_MINUTES", 10))
    DELIVERY_FAILED_QUEUE_BOUND = int(
        os.getenv("DELIVERY_FAILED_QUEUE_BOUND", 20))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


config = Config()
