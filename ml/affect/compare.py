"""Compare the WP-104 SVC and MLP affect classifiers under one fixed evaluation protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import validate_feature_table
from .evaluate import DEFAULT_N_SPLITS, DEPLOYMENT_THRESHOLD, evaluate_held_out, evaluate_ravdess
from .model import build_mlp_pipeline, build_svc_pipeline


def compare_ravdess_models(
    feature_csv: str | Path,
    manifest_csv: str | Path,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
) -> dict[str, object]:
    """Evaluate SVC and MLP on identical speaker-disjoint RAVDESS folds and compare macro-F1."""
    features = validate_feature_table(feature_csv, manifest_csv)
    svc_result = evaluate_ravdess(
        features,
        manifest_csv,
        n_splits=n_splits,
        model_factory=build_svc_pipeline,
    )
    mlp_result = evaluate_ravdess(
        features,
        manifest_csv,
        n_splits=n_splits,
        model_factory=build_mlp_pipeline,
    )
    delta = mlp_result.macro_f1 - svc_result.macro_f1
    winner = "MLP" if delta > 0 else "SVC" if delta < 0 else "Tie"
    return {
        "protocol": {
            "corpus": "RAVDESS",
            "cv_scheme": "GroupKFold",
            "n_splits": n_splits,
            "grouping_key": "speaker_id",
            "feature_count": 88,
            "metric": "macro_f1",
            "deployment_threshold": DEPLOYMENT_THRESHOLD,
        },
        "svc": {
            "macro_f1": svc_result.macro_f1,
            "per_class_f1": svc_result.per_class_f1,
            "confusion_matrix": svc_result.confusion_matrix.tolist(),
        },
        "mlp": {
            "macro_f1": mlp_result.macro_f1,
            "per_class_f1": mlp_result.per_class_f1,
            "confusion_matrix": mlp_result.confusion_matrix.tolist(),
        },
        "comparison": {
            "macro_f1_delta_mlp_minus_svc": delta,
            "winner": winner,
            "svc_go_no_go": "GO" if svc_result.macro_f1 >= DEPLOYMENT_THRESHOLD else "NO-GO",
            "mlp_go_no_go": "GO" if mlp_result.macro_f1 >= DEPLOYMENT_THRESHOLD else "NO-GO",
        },
    }


def write_comparison_evidence(
    result: dict[str, object],
    output_path: str | Path,
) -> Path:
    """Write deterministic JSON evidence for the SVC-versus-MLP comparison."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the model comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ravdess-features", required=True, type=Path)
    parser.add_argument("--ravdess-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--n-splits", default=DEFAULT_N_SPLITS, type=int)
    return parser


def main() -> None:
    """Run the fixed SVC-versus-MLP comparison and write JSON evidence."""
    args = _parser().parse_args()
    result = compare_ravdess_models(
        args.ravdess_features,
        args.ravdess_manifest,
        n_splits=args.n_splits,
    )
    output = write_comparison_evidence(result, args.output)
    comparison = result["comparison"]
    print(f"Wrote {output}")
    print(f"SVC macro-F1: {result['svc']['macro_f1']:.6f}")
    print(f"MLP macro-F1: {result['mlp']['macro_f1']:.6f}")
    print(f"MLP - SVC: {comparison['macro_f1_delta_mlp_minus_svc']:.6f}")
    print(f"Winner: {comparison['winner']}")


if __name__ == "__main__":
    main()
