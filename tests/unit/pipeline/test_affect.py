import numpy as np
import pytest

from pipeline.nodes.affect import AffectDetectionError, make_affect_node


class FakeAffect:
    def __init__(self, level):
        """Initialize the FakeAffect and establish its runtime state."""
        self.level = level
        self.calls = []

    def detect(self, audio, sample_rate):
        """Detect the current affect level from the supplied audio."""
        self.calls.append((audio, sample_rate))
        return self.level


class FailingAffect:
    def detect(self, audio, sample_rate):
        """Simulate a detector failure during a live turn."""
        raise RuntimeError("classifier unavailable")


def test_affect_node_uses_same_audio_contract():
    """Verify that affect node uses same audio contract."""
    detector = FakeAffect("Moderate")
    audio = np.zeros(160, dtype=np.float32)
    result = make_affect_node(detector)({"audio": audio, "sample_rate": 16000})
    assert result == {"affect_level": "Moderate", "degradation_reason": None}
    assert detector.calls == [(audio, 16000)]


def test_affect_node_rejects_invalid_detector_level():
    """Verify that invalid detector output degrades instead of aborting the turn."""
    result = make_affect_node(FakeAffect("medium"))(
        {"audio": [1], "sample_rate": 16000}
    )
    assert result == {"affect_level": "Low", "degradation_reason": "affect_detector_failure"}


def test_affect_node_degrades_when_detector_fails():
    """Verify that detector failures are converted to a safe fallback level."""
    result = make_affect_node(FailingAffect())(
        {"audio": [1], "sample_rate": 16000}
    )
    assert result == {"affect_level": "Low", "degradation_reason": "affect_detector_failure"}


def test_affect_node_rejects_missing_audio():
    """Verify that missing audio remains an input contract error."""
    with pytest.raises(AffectDetectionError):
        make_affect_node(FakeAffect("Low"))({"sample_rate": 16000})


def test_affect_node_preserves_genuine_low_without_degradation():
    """Verify a genuine Low classifier result carries no degradation reason."""
    result = make_affect_node(FakeAffect("Low"))(
        {"audio": [1], "sample_rate": 16000}
    )
    assert result == {"affect_level": "Low", "degradation_reason": None}
