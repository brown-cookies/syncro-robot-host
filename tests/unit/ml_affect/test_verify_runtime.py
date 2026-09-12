"""Tests for the WP-104 runtime verification producer."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import sklearn

from ml.affect.dataset import write_feature_alignment_sidecar
from ml.affect.train import train_from_features, write_evidence
from ml.affect.evaluate import evaluate_held_out
from ml.affect.verify_runtime import verify_runtime, write_runtime_verification


def _write_dataset(tmp_path: Path, name: str, speakers: list[str]):
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


def test_verify_runtime_reports_live_sklearn_version_and_accepted_metrics(tmp_path):
    """The producer must read real evidence, not hand-maintained values."""
    ravdess_features, ravdess_manifest = _write_dataset(tmp_path, "ravdess", ["01", "02", "03", "04"])
    tess_features, tess_manifest = _write_dataset(tmp_path, "tess", ["A", "B"])
    artifact = tmp_path / "affect_svc_v1.joblib"

    model, ravdess = train_from_features(ravdess_features, ravdess_manifest, artifact, n_splits=4)
    tess_matrix = np.loadtxt(tess_features, delimiter=",", skiprows=1)
    tess = evaluate_held_out(model, tess_matrix, tess_manifest, corpus="tess")

    evidence_dir = tmp_path / "evidence"
    write_evidence(
        ravdess,
        tess,
        evidence_dir=evidence_dir,
        artifact_path=artifact,
        n_splits=4,
    )

    payload = verify_runtime(
        model_path=artifact,
        metrics_path=evidence_dir / "metrics.json",
        require_pinned_sklearn=False,
    )

    assert payload["artifact_verification"] == "trained_persisted_loaded_and_sample_predicted"
    assert payload["artifact_version"] == "affect_svc_v1"
    assert payload["required_sklearn_version"] == "1.9.0"
    # This is the exact bug being fixed: verification must record the version actually used to
    # run the check, not a hand-typed, potentially stale value.
    assert payload["verification_sklearn_version"] == sklearn.__version__
    assert payload["ravdess_macro_f1"] == ravdess.macro_f1
    assert payload["tess_macro_f1"] == tess.macro_f1
    assert payload["go_no_go"] in {"GO", "NO-GO"}
    assert payload["threshold"] == 0.70

    output = write_runtime_verification(payload, tmp_path / "runtime_verification.json")
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == payload


def test_verify_runtime_rejects_a_bad_sample_prediction(tmp_path, monkeypatch):
    """An artifact that cannot produce a valid affect label must fail verification loudly."""
    ravdess_features, ravdess_manifest = _write_dataset(tmp_path, "ravdess", ["01", "02", "03", "04"])
    tess_features, tess_manifest = _write_dataset(tmp_path, "tess", ["A", "B"])
    artifact = tmp_path / "affect_svc_v1.joblib"

    model, ravdess = train_from_features(ravdess_features, ravdess_manifest, artifact, n_splits=4)
    tess_matrix = np.loadtxt(tess_features, delimiter=",", skiprows=1)
    tess = evaluate_held_out(model, tess_matrix, tess_manifest, corpus="tess")

    evidence_dir = tmp_path / "evidence"
    write_evidence(
        ravdess,
        tess,
        evidence_dir=evidence_dir,
        artifact_path=artifact,
        n_splits=4,
    )

    import ml.affect.verify_runtime as verify_runtime_module

    class _BadModel:
        def predict(self, _features):
            return ["NotALevel"]

    monkeypatch.setattr(
        verify_runtime_module, "load_model_artifact", lambda _path: _BadModel()
    )

    try:
        verify_runtime(model_path=artifact, metrics_path=evidence_dir / "metrics.json")
    except AssertionError as exc:
        assert "NotALevel" in str(exc)
    else:
        raise AssertionError("Expected verify_runtime to reject an invalid sample prediction")


def test_verify_runtime_fails_loudly_on_malformed_metrics(tmp_path):
    """A metrics.json that doesn't match the expected schema must raise, not KeyError."""
    ravdess_features, ravdess_manifest = _write_dataset(tmp_path, "ravdess", ["01", "02", "03", "04"])
    artifact = tmp_path / "affect_svc_v1.joblib"
    train_from_features(ravdess_features, ravdess_manifest, artifact, n_splits=4)

    bad_metrics = tmp_path / "bad_metrics.json"
    bad_metrics.write_text(json.dumps({"not": "the expected schema"}), encoding="utf-8")

    try:
        verify_runtime(model_path=artifact, metrics_path=bad_metrics)
    except ValueError as exc:
        assert str(bad_metrics) in str(exc)
    else:
        raise AssertionError("Expected a malformed metrics.json to raise ValueError")


def test_verify_runtime_rejects_unpinned_sklearn(tmp_path, monkeypatch):
    """Acceptance verification must not produce evidence from the wrong sklearn version."""
    ravdess_features, ravdess_manifest = _write_dataset(tmp_path, "ravdess", ["01", "02", "03", "04"])
    tess_features, tess_manifest = _write_dataset(tmp_path, "tess", ["A", "B"])
    artifact = tmp_path / "affect_svc_v1.joblib"
    model, ravdess = train_from_features(ravdess_features, ravdess_manifest, artifact, n_splits=4)
    tess_matrix = np.loadtxt(tess_features, delimiter=",", skiprows=1)
    tess = evaluate_held_out(model, tess_matrix, tess_manifest, corpus="tess")
    evidence_dir = tmp_path / "evidence"
    write_evidence(ravdess, tess, evidence_dir=evidence_dir, artifact_path=artifact, n_splits=4)

    import ml.affect.verify_runtime as verify_runtime_module
    monkeypatch.setattr(verify_runtime_module.sklearn, "__version__", "1.8.0")
    try:
        verify_runtime(model_path=artifact, metrics_path=evidence_dir / "metrics.json")
    except RuntimeError as exc:
        assert "pinned scikit-learn version" in str(exc)
    else:
        raise AssertionError("Expected unpinned sklearn runtime to be rejected")
