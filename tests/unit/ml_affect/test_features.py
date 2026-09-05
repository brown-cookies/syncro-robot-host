import numpy as np
import pytest

from ml.affect.features import EXPECTED_FEATURE_COUNT, FeatureExtractionError, extract_features


class FakeFrame:
    def __init__(self, data):
        """Initialize the FakeFrame and establish its runtime state."""
        self.data = np.asarray(data)

    def to_numpy(self, dtype=None, copy=True):
        """Convert the test signal into a NumPy representation."""
        return np.array(self.data, dtype=dtype, copy=copy)


class FakeSmile:
    def process_signal(self, audio, sample_rate):
        """Process the supplied signal through the test feature-extraction boundary."""
        assert sample_rate == 16000
        return FakeFrame(np.arange(EXPECTED_FEATURE_COUNT, dtype=np.float64))


def test_feature_vector_is_88_float_values():
    """Verify that feature vector is 88 float values."""
    result = extract_features(np.ones(1600, dtype=np.float32), 16000, smile=FakeSmile())
    assert result.vector.shape == (88,)
    assert np.issubdtype(result.vector.dtype, np.floating)
    assert result.vector.dtype == np.float64


def test_invalid_audio_is_rejected_before_extraction():
    """Verify that invalid audio is rejected before extraction."""
    with pytest.raises(ValueError):
        extract_features(None, 16000, smile=FakeSmile())
    with pytest.raises(ValueError):
        extract_features(np.ones(10), 0, smile=FakeSmile())


def test_wrong_feature_count_is_named_error():
    """Verify that wrong feature count is named error."""
    class BadSmile(FakeSmile):
        def process_signal(self, audio, sample_rate):
            """Process the supplied signal through the test feature-extraction boundary."""
            return FakeFrame(np.zeros(7))

    with pytest.raises(FeatureExtractionError):
        extract_features(np.ones(1600), 16000, smile=BadSmile())
