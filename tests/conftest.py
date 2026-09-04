from __future__ import annotations

import numpy as np
import pytest

from config.settings import Settings

@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        audio_sample_rate_hz=16_000,
        audio_channels=1,
        audio_capture_seconds=1.0,
        audio_input_device="",
        audio_output_device="",
        ollama_url="http://localhost:11434",
        llm_model="test-model",
        ollama_num_ctx=512,
        ollama_timeout_s=1.0,
        stt_model_size="small",
        stt_compute_type="int8",
        stt_device="cpu",
        piper_model_path="./models/test",
    )

@pytest.fixture
def sample_audio() -> np.ndarray:
    return np.array([0.1, -0.2, 0.3, -0.4], dtype=np.float32)
