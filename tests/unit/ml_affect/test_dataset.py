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
