from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from config.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Verify that settings."""
    return Settings(
        audio_sample_rate_hz=16_000,
        audio_channels=1,
        audio_capture_seconds=1.0,
        audio_input_device="",
        audio_output_device="",
        ollama_url="http://localhost:11434",
        llm_model="test-model",
        ollama_num_ctx=512,
        intent_timeout_s=1.0,
        reasoning_timeout_s=1.0,
        non_llm_timeout_margin_s=1.0,
        stt_model_size="small",
        stt_compute_type="int8",
        stt_device="cpu",
        piper_model_path="./models/test",
    )


@pytest.fixture
def sample_audio() -> np.ndarray:
    """Perform the sample audio operation required by the project."""
    return np.array([0.1, -0.2, 0.3, -0.4], dtype=np.float32)


TESTS_ROOT = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """
    Tag every test with its component, taken from its folder under tests/.

    Every test under tests/unit/ gets the `unit` marker plus one component
    marker, chosen by its folder:

        tests/unit/adapters/     -> `adapters`      (adapters/)
        tests/unit/api/          -> `api`           (api/)
        tests/unit/audio/        -> `audio`         (audio/)
        tests/unit/composition/  -> `composition`   (composition/)
        tests/unit/config/       -> `config`        (config/)
        tests/unit/pipeline/     -> `pipeline`      (pipeline/)
        tests/unit/storage/      -> `storage`       (storage/)
        tests/unit/ml_affect/    -> `ml_affect`     (ml/affect/)
        tests/unit/scripts/      -> `scripts`       (scripts/)

    Every test under tests/integration/ gets the `integration` marker.

    The markers are registered in pytest.ini (with --strict-markers), so a new
    folder under tests/unit/ must also be added there. Select by component with
    `pytest -m api` or `pytest -m "api or storage"`.
    """

    for item in items:
        parts = item.path.resolve().relative_to(TESTS_ROOT).parts
        if parts[0] == "integration":
            item.add_marker(pytest.mark.integration)
        elif parts[0] == "unit" and len(parts) > 2:
            item.add_marker(pytest.mark.unit)
            item.add_marker(getattr(pytest.mark, parts[1]))
