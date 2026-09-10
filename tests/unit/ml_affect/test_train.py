from pathlib import Path

"""Tests for the WP-104 training orchestration."""

import csv
import json

import numpy as np

from ml.affect.dataset import write_feature_alignment_sidecar
from ml.affect.evaluate import evaluate_held_out
from ml.affect.train import train_from_features
from ml.affect.artifacts import load_model_artifact


def _write_dataset(tmp_path, name, speakers):
    """Write a small valid three-class corpus manifest and feature table."""
    manifest = tmp_path / f"{name}_manifest.csv"
    features = tmp_path / f"{name}_features.csv"
    rows = []
    vectors = []
    labels = [("neutral", "Low", 0.0), ("happy", "Moderate", 1.0), ("angry", "High", 2.0)]
    for speaker_index, speaker in enumerate(speakers):
        for clip_index, (source, target, value) in enumerate(labels):
            rows.append(
                [
                    f"clip_{speaker_index}_{clip_index}.wav",
                    "RAVDESS" if name == "ravdess" else "TESS",
                    speaker,
                    source,
                    target,
                ]
            )
            vectors.append([value + speaker_index * 0.01] + [0.0] * 87)

    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["audio_path", "corpus", "speaker_id", "source_label", "target_label"])
        writer.writerows(rows)
    with features.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([f"feature_{index:02d}" for index in range(88)])
        writer.writerows(vectors)
    write_feature_alignment_sidecar(manifest, features)
    return features, manifest


def test_train_from_features_runs_oof_then_persists_final_model(tmp_path):
    """Verify that training evaluates speaker-independent OOF predictions before saving the model."""
    features, manifest = _write_dataset(tmp_path, "ravdess", ["01", "02", "03", "04"])
    artifact = tmp_path / "affect_svc_v1.joblib"

    model, result = train_from_features(features, manifest, artifact, n_splits=4)

    assert artifact.exists()
    assert result.n_splits == 4
    assert result.macro_f1 >= 0.0
    assert result.confusion_matrix.shape == (3, 3)
    assert model.predict(np.zeros((1, 88))).shape == (1,)
    assert load_model_artifact(artifact).predict(np.zeros((1, 88))).shape == (1,)


def test_held_out_evaluation_uses_frozen_model(tmp_path):
    """Verify that a persisted trained pipeline can score an external held-out corpus."""
    train_features, train_manifest = _write_dataset(tmp_path, "ravdess", ["01", "02", "03", "04"])
    tess_features, tess_manifest = _write_dataset(tmp_path, "tess", ["A", "B"])
    artifact = tmp_path / "affect_svc_v1.joblib"
    model, _ = train_from_features(train_features, train_manifest, artifact, n_splits=4)
    held_out = np.loadtxt(tess_features, delimiter=",", skiprows=1)

    result = evaluate_held_out(model, held_out, tess_manifest, corpus="tess")

    assert result.n_splits is None
    assert 0.0 <= result.macro_f1 <= 1.0
    assert result.confusion_matrix.shape == (3, 3)


def test_method_note_is_self_contained(tmp_path):
    """Verify generated method notes do not depend on an external template."""
    from ml.affect.train import _method_note
    from ml.affect.evaluate import EvaluationResult

    result = EvaluationResult(
        macro_f1=0.632258,
        per_class_f1={
            "Low": 0.652666,
            "Moderate": 0.474359,
            "High": 0.769750,
        },
        confusion_matrix=np.zeros((3, 3), dtype=int),
        y_true=["Low"],
        y_pred=["Low"],
        n_splits=6,
    )
    tess = EvaluationResult(
        macro_f1=0.199983,
        per_class_f1={"Low": 0.0, "Moderate": 0.0, "High": 0.599950},
        confusion_matrix=np.zeros((3, 3), dtype=int),
        y_true=["High"],
        y_pred=["High"],
        n_splits=None,
    )

    generated = _method_note(
        result,
        tess,
        artifact_path=tmp_path / "affect_svc_v1.joblib",
        n_splits=6,
    )

    assert generated.startswith("# WP-104 Affect Classifier Method Note")
    for heading in (
        "## Dataset",
        "## Classifier",
        "## RAVDESS Evaluation",
        "## TESS Held-Out Evaluation",
        "## Go / No-Go",
    ):
        assert heading in generated

    assert "<" not in generated
    # Regression: the classifier pipeline description must not over-escape quotes.
    assert 'SVC(kernel="rbf", class_weight="balanced")' in generated
    assert '\\"' not in generated
    # No comparison artifact was supplied, so the status must stay honest, not claim a run.
    assert "MLPClassifier comparison: not run; SVC is the fixed shipped classifier." in generated


def test_method_note_reports_measured_mlp_comparison_when_available(tmp_path):
    """The MLP comparison status must come from real evidence, never a hardcoded literal."""
    from ml.affect.train import _method_note
    from ml.affect.evaluate import EvaluationResult

    result = EvaluationResult(
        macro_f1=0.632258,
        per_class_f1={"Low": 0.652666, "Moderate": 0.474359, "High": 0.769750},
        confusion_matrix=np.zeros((3, 3), dtype=int),
        y_true=["Low"],
        y_pred=["Low"],
        n_splits=6,
    )
    tess = EvaluationResult(
        macro_f1=0.199983,
        per_class_f1={"Low": 0.0, "Moderate": 0.0, "High": 0.599950},
        confusion_matrix=np.zeros((3, 3), dtype=int),
        y_true=["High"],
        y_pred=["High"],
        n_splits=None,
    )
    comparison_path = tmp_path / "svc_vs_mlp_comparison.json"
    comparison_path.write_text(
        json.dumps(
            {
                "protocol": {"n_splits": 6},
                "svc": {"macro_f1": 0.6322582442748598},
                "mlp": {"macro_f1": 0.6252536484681824},
                "comparison": {
                    "macro_f1_delta_mlp_minus_svc": -0.007004595806677338,
                    "winner": "SVC",
                },
            }
        ),
        encoding="utf-8",
    )

    generated = _method_note(
        result,
        tess,
        artifact_path=tmp_path / "affect_svc_v1.joblib",
        n_splits=6,
        mlp_comparison_path=comparison_path,
    )

    assert (
        "MLPClassifier comparison: run; SVC 0.632258 vs MLP 0.625254 on the identical "
        "6-fold GroupKFold protocol; SVC remains selected." in generated
    )
    assert "not run" not in generated


def test_method_note_fails_loudly_on_a_malformed_comparison_file(tmp_path):
    """A corrupt comparison file must raise, not silently report a false 'not run' status."""
    from ml.affect.train import _method_note
    from ml.affect.evaluate import EvaluationResult

    result = EvaluationResult(
        macro_f1=0.632258,
        per_class_f1={"Low": 0.652666, "Moderate": 0.474359, "High": 0.769750},
        confusion_matrix=np.zeros((3, 3), dtype=int),
        y_true=["Low"],
        y_pred=["Low"],
        n_splits=6,
    )
    tess = EvaluationResult(
        macro_f1=0.199983,
        per_class_f1={"Low": 0.0, "Moderate": 0.0, "High": 0.599950},
        confusion_matrix=np.zeros((3, 3), dtype=int),
        y_true=["High"],
        y_pred=["High"],
        n_splits=None,
    )
    comparison_path = tmp_path / "svc_vs_mlp_comparison.json"
    comparison_path.write_text(json.dumps({"not": "the expected schema"}), encoding="utf-8")

    try:
        _method_note(
            result,
            tess,
            artifact_path=tmp_path / "affect_svc_v1.joblib",
            n_splits=6,
            mlp_comparison_path=comparison_path,
        )
    except ValueError as exc:
        assert str(comparison_path) in str(exc)
    else:
        raise AssertionError("Expected a malformed comparison file to raise ValueError")
