import numpy as np
import pytest

from adapters.affect.classifier_detector import ClassifierAffectDetector


class FakeModel:
    def predict(self, values):
        """Perform the predict operation required by the project."""
        assert values.shape == (1, 88)
        return np.array(["Moderate"])


def test_detector_returns_allowed_level(monkeypatch):
    """Verify that detector returns allowed level."""
    detector = object.__new__(ClassifierAffectDetector)
    detector.model_path = None
    detector.model = FakeModel()
    monkeypatch.setattr(
        "adapters.affect.classifier_detector.extract_features",
        lambda audio, sample_rate: type("R", (), {"vector": np.zeros(88), "elapsed_seconds": 0.001})(),
    )
    assert detector.detect(np.zeros(16000, dtype=np.float32), 16000) == "Moderate"


def test_detector_rejects_bad_input():
    """Verify that detector rejects bad input."""
    detector = object.__new__(ClassifierAffectDetector)
    detector.model_path = None
    detector.model = FakeModel()
    with pytest.raises(ValueError):
        detector.detect(None, 16000)
    with pytest.raises(ValueError):
        detector.detect(np.zeros(10), 0)
