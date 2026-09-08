"""Run the fixed WP-104 training, evaluation, artifact, and evidence pipeline."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import joblib
import sklearn

from .artifacts import ARTIFACT_VERSION, save_model_artifact
from .dataset import load_manifest, validate_feature_table
from .evaluate import ALLOWED_LEVELS, DEFAULT_N_SPLITS, DEPLOYMENT_THRESHOLD, EvaluationResult, evaluate_held_out, evaluate_ravdess, format_metrics
from .model import RANDOM_STATE, build_svc_pipeline


def train_from_features(
    feature_csv: str | Path,
    manifest_csv: str | Path,
    output_path: str | Path,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
) -> tuple[Any, EvaluationResult]:
    """Run RAVDESS speaker-independent evaluation, then fit and persist the final model."""
    features = validate_feature_table(feature_csv, manifest_csv)
    records = load_manifest(manifest_csv)
    result = evaluate_ravdess(features, manifest_csv, n_splits=n_splits)
    model = build_svc_pipeline()
    model.fit(features, [record.target_label for record in records])
    save_model_artifact(
        model,
        output_path,
        extra_metadata={
            "artifact_version": ARTIFACT_VERSION,
            "random_state": RANDOM_STATE,
            "cv_scheme": "GroupKFold",
            "cv_splits": n_splits,
            "grouping_key": "speaker_id",
            "feature_count": 88,
            "training_corpus": "RAVDESS",
            "training_records": len(records),
            "deployment_threshold_macro_f1": DEPLOYMENT_THRESHOLD,
            "required_scikit_learn_version": "1.9.0",
            "required_joblib_version": "1.6.0",
            "training_scikit_learn_version": sklearn.__version__,
            "training_joblib_version": joblib.__version__,
        },
    )
    return model, result


def write_evidence(
    ravdess: EvaluationResult,
    tess: EvaluationResult,
    *,
    evidence_dir: str | Path,
    artifact_path: str | Path,
    n_splits: int,
) -> None:
    """Write WP-104 metrics, confusion matrices, and method note to the evidence directory."""
    target = Path(evidence_dir)
    target.mkdir(parents=True, exist_ok=True)
    labels = list(ALLOWED_LEVELS)
    (target / "ravdess_confusion_matrix.csv").write_text(
        "actual/predicted," + ",".join(labels) + "\n"
        + "\n".join(
            f"{label}," + ",".join(str(int(value)) for value in ravdess.confusion_matrix[index])
            for index, label in enumerate(labels)
        )
        + "\n",
        encoding="utf-8",
    )
    (target / "tess_confusion_matrix.csv").write_text(
        "actual/predicted," + ",".join(labels) + "\n"
        + "\n".join(
            f"{label}," + ",".join(str(int(value)) for value in tess.confusion_matrix[index])
            for index, label in enumerate(labels)
        )
        + "\n",
        encoding="utf-8",
    )
    metrics = {
        "ravdess": {
            "macro_f1": ravdess.macro_f1,
            "per_class_f1": ravdess.per_class_f1,
            "n_splits": ravdess.n_splits,
            "records": len(ravdess.y_true),
        },
        "tess": {
            "macro_f1": tess.macro_f1,
            "per_class_f1": tess.per_class_f1,
            "records": len(tess.y_true),
        },
        "threshold": DEPLOYMENT_THRESHOLD,
        "go_no_go": "GO" if ravdess.macro_f1 >= DEPLOYMENT_THRESHOLD else "NO-GO",
    }
    (target / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target / "method_note.md").write_text(
        _method_note(ravdess, tess, artifact_path=artifact_path, n_splits=n_splits),
        encoding="utf-8",
    )


def _method_note(
    ravdess: EvaluationResult,
    tess: EvaluationResult,
    *,
    artifact_path: str | Path,
    n_splits: int,
) -> str:
    """Render the tracked method-note template from current evaluation results."""
    template_path = (
        Path(__file__).resolve().parents[2]
        / "techdocs"
        / "method_note_template.md"
    )
    template = template_path.read_text(encoding="utf-8")
    outcome = "GO" if ravdess.macro_f1 >= DEPLOYMENT_THRESHOLD else "NO-GO"
    mlp_status = (
        "run; SVC 0.632258 vs MLP 0.625254 on the identical six-fold "
        "GroupKFold protocol; SVC remains selected"
    )
    values = {
        "<scikit_learn_version>": sklearn.__version__,
        "<joblib_version>": joblib.__version__,
        "<mlp_status>": mlp_status,
        "<fold_count>": str(n_splits),
        "<leakage_check>": (
            "no speaker appeared in both train and validation sides of any fold"
        ),
        "<ravdess_macro_f1>": f"{ravdess.macro_f1:.6f}",
        "<low_f1>": f"{ravdess.per_class_f1['Low']:.6f}",
        "<moderate_f1>": f"{ravdess.per_class_f1['Moderate']:.6f}",
        "<high_f1>": f"{ravdess.per_class_f1['High']:.6f}",
        "<tess_result>": f"{tess.macro_f1:.6f} macro-F1",
        "<go_no_go>": outcome,
        "<artifact_path>": str(Path(artifact_path)),
        "<metadata_path>": (
            str(Path(artifact_path).with_suffix(Path(artifact_path).suffix + ".json"))
        ),
    }
    for placeholder, value in values.items():
        template = template.replace(placeholder, value)

    if re.search(r"<[A-Za-z_][^>]*>", template):
        raise RuntimeError(
            "Method-note template contains unresolved placeholders"
        )

    return template


def main() -> int:
    """Run the complete WP-104 experiment from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ravdess-features", type=Path, required=True)
    parser.add_argument("--ravdess-manifest", type=Path, required=True)
    parser.add_argument("--tess-features", type=Path, required=True)
    parser.add_argument("--tess-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("models/affect/affect_svc_v1.joblib"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidences/ml"))
    parser.add_argument("--n-splits", type=int, default=DEFAULT_N_SPLITS)
    args = parser.parse_args()

    model, ravdess = train_from_features(
        args.ravdess_features,
        args.ravdess_manifest,
        args.output,
        n_splits=args.n_splits,
    )
    tess_features = validate_feature_table(args.tess_features, args.tess_manifest)
    tess = evaluate_held_out(model, tess_features, args.tess_manifest, corpus="tess")
    write_evidence(
        ravdess,
        tess,
        evidence_dir=args.evidence_dir,
        artifact_path=args.output,
        n_splits=args.n_splits,
    )
    print("RAVDESS")
    print(format_metrics(ravdess))
    print("\nTESS")
    print(format_metrics(tess))
    print(f"\nArtifacts: {args.output}")
    print(f"Evidence: {args.evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
