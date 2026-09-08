import csv

import numpy as np

import ml.affect.evaluate as evaluate


def test_groupkfold_has_speaker_disjoint_splits(tmp_path, monkeypatch):
    """Verify that every evaluation fold keeps speakers entirely on one side."""
    speakers = ["s1", "s2", "s3", "s4"]
    rows = []
    features = []
    labels = [("neutral", "Low"), ("happy", "Moderate"), ("angry", "High")]
    for i, speaker in enumerate(speakers):
        for j, (source_label, target_label) in enumerate(labels):
            rows.append([f"x_{i}_{j}.wav", "RAVDESS", speaker, source_label, target_label])
            features.append([float(i), float(j)] + [0.0] * 86)
    manifest = tmp_path / "ravdess.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["audio_path", "corpus", "speaker_id", "source_label", "target_label"])
        writer.writerows(rows)

    class GuardedModel:
        def __init__(self):
            """Initialize the fold-isolation model double."""
            self.train_speakers = set()

        def fit(self, x, y):
            """Record the speaker ids represented by the training partition."""
            self.train_speakers = {int(value) for value in np.asarray(x)[:, 0]}
            return self

        def predict(self, x):
            """Reject any validation partition whose speakers leaked into training."""
            test_speakers = {int(value) for value in np.asarray(x)[:, 0]}
            assert self.train_speakers.isdisjoint(test_speakers)
            return np.asarray(["Low"] * len(x), dtype=object)

    monkeypatch.setattr(evaluate, "build_svc_pipeline", GuardedModel)
    result = evaluate.evaluate_ravdess(np.asarray(features), manifest, n_splits=4)

    assert result.n_splits == 4
    assert len(result.y_true) == len(rows)
    assert 0.0 <= result.macro_f1 <= 1.0
    assert result.confusion_matrix.shape == (3, 3)
