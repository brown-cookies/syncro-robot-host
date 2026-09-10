"""Verify the shipped WP-104 affect artifact loads and predicts, and record the check.

`evidences/ml/experiment/runtime_verification.json` previously had no committed producer and
was hand-edited, which let it drift to a scikit-learn version that matched neither the pinned
requirement nor the version actually used to train/evaluate the shipped artifact. This module
is that producer: it loads the persisted artifact, confirms it predicts a valid label, and
folds in the already-accepted RAVDESS/TESS metrics so the file always reflects real evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import sklearn

from .artifacts import load_model_artifact, read_artifact_metadata
from .evaluate import ALLOWED_LEVELS

SAMPLE_FEATURE_COUNT = 88


def verify_runtime(
    *,
    model_path: str | Path,
    metrics_path: str | Path,
    require_pinned_sklearn: bool = True,
) -> dict[str, object]:
    """Load the persisted artifact, run a sample prediction, and assemble verification evidence."""
    model = load_model_artifact(model_path)
    metadata = read_artifact_metadata(model_path)

    sample = np.zeros((1, SAMPLE_FEATURE_COUNT), dtype=np.float64)
    prediction = model.predict(sample)
    label = str(prediction[0])
    if label not in ALLOWED_LEVELS:
        raise AssertionError(
            f"Sample prediction returned an unexpected affect level: {label!r}"
        )

    metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
    try:
        go_no_go = metrics["go_no_go"]
        ravdess_macro_f1 = metrics["ravdess"]["macro_f1"]
        tess_macro_f1 = metrics["tess"]["macro_f1"]
        threshold = metrics["threshold"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"Metrics evidence at {metrics_path} is not a valid ml.affect.train "
            "metrics.json payload. Regenerate it with `python -m ml.affect.train ...`."
        ) from exc

    required_sklearn_version = str(metadata["required_scikit_learn_version"])
    if require_pinned_sklearn and sklearn.__version__ != required_sklearn_version:
        raise RuntimeError(
            "Runtime verification requires the pinned scikit-learn version "
            f"{required_sklearn_version}; installed {sklearn.__version__}. "
            "Run this producer in the repository's pinned environment."
        )

    return {
        "artifact_verification": "trained_persisted_loaded_and_sample_predicted",
        "artifact_version": metadata["artifact_version"],
        "go_no_go": go_no_go,
        "ravdess_macro_f1": ravdess_macro_f1,
        "required_sklearn_version": required_sklearn_version,
        "selected_model": 'SVC(kernel="rbf", class_weight="balanced")',
        "tess_macro_f1": tess_macro_f1,
        "threshold": threshold,
        "verification_sklearn_version": sklearn.__version__,
    }


def write_runtime_verification(payload: dict[str, object], output_path: str | Path) -> Path:
    """Write deterministic JSON evidence for the runtime verification check."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the runtime verification producer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", type=Path, default=Path("models/affect/affect_svc_v1.joblib")
    )
    parser.add_argument(
        "--metrics", type=Path, default=Path("evidences/ml/experiment/metrics.json")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evidences/ml/experiment/runtime_verification.json"),
    )
    return parser


def main() -> int:
    """Run runtime verification and write its evidence file from the command line."""
    args = _parser().parse_args()
    payload = verify_runtime(model_path=args.model, metrics_path=args.metrics)
    target = write_runtime_verification(payload, args.output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Evidence: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
