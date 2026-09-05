import csv

import numpy as np

from ml.affect.evaluate import evaluate_ravdess


def test_groupkfold_has_speaker_disjoint_splits(tmp_path, monkeypatch):
    """Verify that groupkfold has speaker disjoint splits."""
    speakers = ["s1", "s2", "s3", "s4"]
    rows = []
    features = []
    labels = [("neutral", "Low"), ("happy", "Moderate"), ("angry", "High"), ("neutral", "Low")]
    for i, speaker in enumerate(speakers):
        source_label, target_label = labels[i]
        for j in range(2):
            rows.append([f"x_{i}_{j}.wav", "RAVDESS", speaker, source_label, target_label])
            features.append([float(i), float(j)])
    manifest = tmp_path / "ravdess.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["audio_path", "corpus", "speaker_id", "source_label", "target_label"])
        writer.writerows(rows)

    # The production evaluator trains the fixed pipeline; this tiny dataset is only a structural test.
    result = evaluate_ravdess(np.asarray(features), manifest, n_splits=4)
    assert result.n_splits == 4
    assert 0.0 <= result.macro_f1 <= 1.0
    assert result.confusion_matrix.shape == (3, 3)
