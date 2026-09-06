import csv

import numpy as np
import pytest

from ml.affect.extract_features import (
    FEATURE_COLUMNS,
    extract_manifest_features,
    write_feature_table,
)
from ml.affect.features import FeatureExtractionResult


def test_manifest_extraction_preserves_record_order_and_reports_progress(tmp_path, capsys, monkeypatch):
    """Verify batch extraction preserves manifest order and reports progress."""
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "audio_path,corpus,speaker_id,source_label,target_label\n"
        "a.wav,ravdess,01,neutral,Low\n"
        "b.wav,ravdess,02,neutral,Low\n",
        encoding="utf-8",
    )
    (tmp_path / "a.wav").write_bytes(b"a")
    (tmp_path / "b.wav").write_bytes(b"b")
    monkeypatch.setattr(
        "ml.affect.extract_features._load_audio",
        lambda path: (np.ones(1600, dtype=np.float32), 16000),
    )

    calls = []

    def fake_extractor(audio, sample_rate):
        """Record each extraction invocation and return a deterministic feature vector."""
        calls.append(len(calls))
        return FeatureExtractionResult(
            vector=np.full(88, float(len(calls))),
            elapsed_seconds=0.0,
        )

    matrix = extract_manifest_features(
        manifest, tmp_path, extractor=fake_extractor, progress_every=1)

    assert matrix.shape == (2, 88)
    assert np.all(matrix[0] == 1.0)
    assert np.all(matrix[1] == 2.0)
    assert calls == [0, 1]
    output = capsys.readouterr().out
    assert "Starting feature extraction: 2 files" in output
    assert "2/2" in output


def test_feature_table_has_exactly_88_columns(tmp_path):
    """Verify that the persisted feature table has the fixed 88-column schema."""
    output = tmp_path / "features.csv"
    write_feature_table(np.zeros((2, 88), dtype=np.float64), output)

    with output.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == list(FEATURE_COLUMNS)
    assert len(rows[0]) == 88
    assert len(rows) == 3


def test_feature_table_rejects_wrong_width(tmp_path):
    """Verify that feature tables reject matrices with the wrong number of columns."""
    with pytest.raises(ValueError, match="88"):
        write_feature_table(np.zeros((1, 87)), tmp_path / "bad.csv")
