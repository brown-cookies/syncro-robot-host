import numpy as np
import pytest

from pipeline.nodes.affect import AffectDetectionError, make_affect_node


class FakeAffect:
    def __init__(self, level):
        self.level = level
        self.calls = []

    def detect(self, audio, sample_rate):
        self.calls.append((audio, sample_rate))
        return self.level


def test_affect_node_uses_same_audio_contract():
    detector = FakeAffect("Moderate")
    audio = np.zeros(160, dtype=np.float32)
    result = make_affect_node(detector)({"audio": audio, "sample_rate": 16000})
    assert result == {"affect_level": "Moderate"}
    assert detector.calls == [(audio, 16000)]


def test_affect_node_rejects_invalid_level():
    with pytest.raises(AffectDetectionError):
        make_affect_node(FakeAffect("medium"))({"audio": [1], "sample_rate": 16000})

