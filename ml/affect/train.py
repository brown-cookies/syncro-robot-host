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
    mlp_comparison_path: str | Path | None = None,
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
        _method_note(
            ravdess,
            tess,
            artifact_path=artifact_path,
            n_splits=n_splits,
            mlp_comparison_path=mlp_comparison_path,
        ),
        encoding="utf-8",
    )


def _mlp_comparison_status(comparison_path: str | Path | None) -> str:
    """Describe the MLP comparison status from committed comparison evidence, if present.

    The status is derived from the `ml.affect.compare` output rather than hardcoded, so the
    method note cannot drift into a false claim once a comparison has actually been run.
    """
    if comparison_path is None:
        return "not run; SVC is the fixed shipped classifier."
    path = Path(comparison_path)
    if not path.exists():
        return "not run; SVC is the fixed shipped classifier."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        svc_f1 = payload["svc"]["macro_f1"]
        mlp_f1 = payload["mlp"]["macro_f1"]
        winner = payload["comparison"]["winner"]
        n_splits = payload["protocol"]["n_splits"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        # A comparison file exists but cannot be read as real evidence. Reporting "not run"
        # here would repeat the original bug in a new form (a false claim in the method note),
        # so fail loudly instead and point at how to fix it.
        raise ValueError(
            f"MLP comparison evidence at {path} exists but is not a valid "
            "ml.affect.compare payload. Regenerate it with `python -m ml.affect.compare "
            "...` or pass a different --mlp-comparison path."
        ) from exc
    return (
        f"run; SVC {svc_f1:.6f} vs MLP {mlp_f1:.6f} on the identical "
        f"{n_splits}-fold GroupKFold protocol; {winner} remains selected."
    )


def _method_note(
    ravdess: EvaluationResult,
    tess: EvaluationResult,
    *,
    artifact_path: str | Path,
    n_splits: int,
    mlp_comparison_path: str | Path | None = None,
) -> str:
    """Build the reproducibility note containing the fixed method and measured results."""
    outcome = "GO" if ravdess.macro_f1 >= DEPLOYMENT_THRESHOLD else "NO-GO"
    scope_down = (
        "The measured macro-F1 is below 0.70; report the classifier as the best measured prototype signal and do not describe it as a validated clinical stress detector."
        if outcome == "NO-GO"
        else "The measured macro-F1 clears the 0.70 deployment gate under the specified speaker-independent evaluation."
    )
    per_class = "\n".join(
        f"- {label}: {ravdess.per_class_f1[label]:.6f}" for label in ALLOWED_LEVELS
    )
    tess_per_class = "\n".join(
        f"- {label}: {tess.per_class_f1[label]:.6f}" for label in ALLOWED_LEVELS
    )
    mlp_status = _mlp_comparison_status(mlp_comparison_path)
    return f"""# WP-104 Affect Classifier Method Note\n\n## Dataset\n\n- RAVDESS: 1,440 clips / 24 speakers; primary evaluation corpus.\n- TESS: 2,800 clips / 2 speakers; held-out generalisation check only.\n- Audio normalization: 16 kHz, mono.\n- Feature table: exactly 88 eGeMAPSv02 Functionals features.\n- Label mapping: see `techdocs/label_mapping.md`.\n\n## Classifier\n\n- Pipeline: `StandardScaler -> SVC(kernel="rbf", class_weight="balanced")`.\n- Random state: {RANDOM_STATE}.\n- scikit-learn used for this run: {sklearn.__version__}.\n- joblib used for this run: {joblib.__version__}.\n- Shipped artifact: `{Path(artifact_path)}`.\n- Artifact version: `{ARTIFACT_VERSION}`.\n- MLPClassifier comparison: {mlp_status}\n\n## RAVDESS Evaluation\n\n- Scheme: `GroupKFold`.\n- Folds: {n_splits}.\n- Grouping key: `speaker_id`.\n- Leakage check: no speaker appeared in both train and validation sides of any fold.\n- Macro-F1: **{ravdess.macro_f1:.6f}**.\n- Per-class F1:\n{per_class}\n\n### Confusion matrix\n\nClass order: `Low, Moderate, High`. See `ravdess_confusion_matrix.csv`.\n\n```text\n{format_metrics(ravdess)}\n```\n\n## TESS Held-Out Evaluation\n\n- TESS was not included in RAVDESS GroupKFold.\n- Macro-F1: **{tess.macro_f1:.6f}**.\n- Per-class F1:\n{tess_per_class}\n\n### Confusion matrix\n\nClass order: `Low, Moderate, High`. See `tess_confusion_matrix.csv`.\n\n```text\n{format_metrics(tess)}\n```\n\n## Go / No-Go\n\nThreshold: **macro-F1 >= {DEPLOYMENT_THRESHOLD:.2f}**.\n\nMeasured outcome: **{outcome}**.\n\n{scope_down}\n"""


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
    parser.add_argument(
        "--mlp-comparison",
        type=Path,
        default=None,
        help=(
            "Path to the ml.affect.compare JSON evidence. When given (or when found at "
            "<evidence-dir>/svc_vs_mlp_comparison.json), the method note reports the actual "
            "measured MLP comparison instead of a hardcoded 'not run' status."
        ),
    )
    args = parser.parse_args()

    mlp_comparison_path = args.mlp_comparison
    if mlp_comparison_path is None:
        mlp_comparison_path = args.evidence_dir / "svc_vs_mlp_comparison.json"

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
        mlp_comparison_path=mlp_comparison_path,
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
