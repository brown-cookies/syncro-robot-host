import csv

import pytest

from ml.affect.dataset import verify_manifest


def _write_manifest(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["audio_path", "corpus", "speaker_id", "source_label", "target_label"])
        writer.writerows(rows)


def test_manifest_verification_accepts_contract_shape(tmp_path):
    rows = []
    emotions = [("neutral", "Low"), ("calm", "Low"), ("happy", "Moderate"), ("sad", "Moderate"),
                ("angry", "High"), ("fearful", "High"), ("disgust", "High"), ("surprised", "High")]
    for speaker_index in range(1, 25):
        for emotion, level in emotions:
            rows.append([f"Actor_{speaker_index:02d}/clip_{emotion}_{speaker_index}.wav", "ravdess", f"{speaker_index:02d}", emotion, level])
    # Eight rows per speaker are not the real corpus count; pad with valid duplicate-label combinations.
    while len(rows) < 1440:
        index = len(rows) % 24 + 1
        emotion, level = emotions[len(rows) % len(emotions)]
        rows.append([f"Actor_{index:02d}/extra_{len(rows)}.wav", "ravdess", f"{index:02d}", emotion, level])

    path = tmp_path / "ravdess.csv"
    _write_manifest(path, rows)
    result = verify_manifest(path, expected_corpus="ravdess")

    assert result.record_count == 1440
    assert result.speaker_count == 24
    assert result.source_label_count == 8
    assert result.target_label_counts.keys() == {"Low", "Moderate", "High"}


def test_manifest_verification_rejects_wrong_source_label_set(tmp_path):
    rows = [["Actor_01/a.wav", "ravdess", "01", "neutral", "Low"]]
    path = tmp_path / "ravdess.csv"
    _write_manifest(path, rows)

    with pytest.raises(ValueError, match="source-label set mismatch"):
        verify_manifest(path, expected_corpus="ravdess")


def test_manifest_verification_rejects_target_label_mismatch(tmp_path):
    path = tmp_path / "ravdess.csv"
    _write_manifest(path, [["Actor_01/a.wav", "ravdess", "01", "angry", "Moderate"]])

    with pytest.raises(ValueError, match="Manifest label mismatch"):
        verify_manifest(path, expected_corpus="ravdess")


def test_manifest_rejects_windows_path_separator(tmp_path):
    """Verify that canonical manifests reject Windows-only path separators."""
    rows = []
    emotions = [("neutral", "Low"), ("calm", "Low"), ("happy", "Moderate"), ("sad", "Moderate"),
                ("angry", "High"), ("fearful", "High"), ("disgust", "High"), ("surprised", "High")]
    for speaker_index in range(1, 25):
        for emotion, level in emotions:
            rows.append([f"Actor_{speaker_index:02d}\\clip_{emotion}_{speaker_index}.wav", "ravdess", f"{speaker_index:02d}", emotion, level])
    while len(rows) < 1440:
        index = len(rows) % 24 + 1
        emotion, level = emotions[len(rows) % len(emotions)]
        rows.append([f"Actor_{index:02d}/extra_{len(rows)}.wav", "ravdess", f"{index:02d}", emotion, level])
    path = tmp_path / "ravdess.csv"
    _write_manifest(path, rows)
    with pytest.raises(ValueError, match="POSIX separators"):
        verify_manifest(path, expected_corpus="ravdess")


def test_feature_table_validation_requires_alignment_sidecar(tmp_path):
    """Verify that feature tables cannot be consumed without alignment metadata."""
    feature_path = tmp_path / "ravdess.csv"
    feature_path.write_text(
        ",".join(f"feature_{i:02d}" for i in range(88)) + "\n"
        + ",".join(["0.0"] * 88) + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    _write_manifest(manifest, [["clip.wav", "tess", "YAF", "neutral", "Low"]])
    with pytest.raises(ValueError, match="Feature alignment sidecar not found"):
        from ml.affect.dataset import validate_feature_table
        validate_feature_table(feature_path, manifest)


def test_feature_table_validation_rejects_manifest_fingerprint_mismatch(tmp_path):
    """Verify that reordered or changed manifest metadata cannot reuse a feature table."""
    from ml.affect.dataset import validate_feature_table, write_feature_alignment_sidecar

    feature_path = tmp_path / "ravdess.csv"
    feature_path.write_text(
        ",".join(f"feature_{i:02d}" for i in range(88)) + "\n"
        + ",".join(["0.0"] * 88) + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    _write_manifest(manifest, [["clip.wav", "tess", "YAF", "neutral", "Low"]])
    write_feature_alignment_sidecar(manifest, feature_path)
    _write_manifest(manifest, [["other.wav", "tess", "YAF", "neutral", "Low"]])

    with pytest.raises(ValueError, match="alignment mismatch"):
        validate_feature_table(feature_path, manifest)
