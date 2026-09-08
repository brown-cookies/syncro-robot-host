import csv

from ml.affect.compare import compare_ravdess_models


def test_compare_reports_both_models_on_same_groupkfold(tmp_path):
    """Verify that comparison evidence contains both model scores and the metric delta."""
    manifest = tmp_path / "ravdess.csv"
    features = tmp_path / "ravdess_features.csv"
    labels = [("neutral", "Low"), ("happy", "Moderate"), ("angry", "High")]
    rows = []
    vectors = []
    for speaker_index in range(4):
        for clip_index, (source, target) in enumerate(labels):
            rows.append([f"clip_{speaker_index}_{clip_index}.wav", "RAVDESS", f"s{speaker_index}", source, target])
            vectors.append([speaker_index, clip_index] + [0.0] * 86)
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["audio_path", "corpus", "speaker_id", "source_label", "target_label"])
        writer.writerows(rows)
    with features.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([f"feature_{index:02d}" for index in range(88)])
        writer.writerows(vectors)
    from ml.affect.dataset import write_feature_alignment_sidecar
    write_feature_alignment_sidecar(manifest, features)

    result = compare_ravdess_models(features, manifest, n_splits=4)

    assert result["protocol"]["n_splits"] == 4
    assert set(result) == {"protocol", "svc", "mlp", "comparison"}
    assert 0.0 <= result["svc"]["macro_f1"] <= 1.0
    assert 0.0 <= result["mlp"]["macro_f1"] <= 1.0
    assert result["comparison"]["winner"] in {"SVC", "MLP", "Tie"}
