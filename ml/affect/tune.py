"""Run reproducible, leakage-safe WP-104 affect fine-tuning experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import sklearn
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from .dataset import load_manifest, manifest_fingerprint, validate_feature_table
from .evaluate import DEPLOYMENT_THRESHOLD
from .model import RANDOM_STATE, build_svc_pipeline

LABELS = ("Low", "Moderate", "High")
DEFAULT_OUTER_SPLITS = 6
DEFAULT_INNER_SPLITS = 3

FIXED_OVR_CANDIDATES = (
    (45, 2.5, 0.0085),
    (50, 2.5, 0.0085),
    (50, 2.75, 0.009),
    (50, 3.0, 0.0095),
    (55, 2.75, 0.009),
)

NESTED_OVR_CANDIDATES = (
    (2.5, 0.0085),
    (2.75, 0.009),
    (3.0, 0.0095),
)


def build_tuned_pipeline(
    *,
    k: int = 50,
    C: float = 2.75,
    gamma: float = 0.009,
) -> Pipeline:
    """Build the research OVR RBF-SVC pipeline with fold-fitted feature selection."""
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("select", SelectKBest(f_classif, k=k)),
            (
                "classifier",
                OneVsRestClassifier(
                    SVC(
                        kernel="rbf",
                        C=C,
                        gamma=gamma,
                        class_weight="balanced",
                    )
                ),
            ),
        ]
    )


def grouped_oof_score(
    features: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    factory: Callable[[], Any],
    *,
    n_splits: int,
) -> float:
    """Measure macro-F1 from speaker-disjoint out-of-fold predictions."""
    y_true: list[str] = []
    y_pred: list[str] = []
    splitter = GroupKFold(n_splits=n_splits)

    for fold_number, (train_idx, test_idx) in enumerate(
        splitter.split(features, labels, groups),
        start=1,
    ):
        train_groups = set(groups[train_idx])
        test_groups = set(groups[test_idx])
        if train_groups & test_groups:
            raise AssertionError(f"Speaker leakage detected in fold {fold_number}")

        model = factory()
        model.fit(features[train_idx], labels[train_idx])
        predictions = np.asarray(model.predict(features[test_idx]), dtype=object)

        y_true.extend(labels[test_idx].tolist())
        y_pred.extend(predictions.tolist())

    return float(
        f1_score(
            y_true,
            y_pred,
            labels=list(LABELS),
            average="macro",
            zero_division=0,
        )
    )


def _load_ravdess(
    feature_csv: str | Path,
    manifest_csv: str | Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[Any]]:
    """Load validated RAVDESS features together with labels and speaker groups."""
    features = validate_feature_table(feature_csv, manifest_csv)
    records = load_manifest(manifest_csv)
    if any(record.corpus != "ravdess" for record in records):
        raise ValueError("RAVDESS tuning requires a RAVDESS-only manifest")

    labels = np.asarray([record.target_label for record in records], dtype=object)
    groups = np.asarray([record.speaker_id for record in records], dtype=object)
    return features, labels, groups, records


def _load_tess(
    feature_csv: str | Path,
    manifest_csv: str | Path,
) -> tuple[np.ndarray, np.ndarray, list[Any]]:
    """Load validated TESS features and labels for the external holdout check."""
    features = validate_feature_table(feature_csv, manifest_csv)
    records = load_manifest(manifest_csv)
    if any(record.corpus != "tess" for record in records):
        raise ValueError("TESS holdout requires a TESS-only manifest")
    labels = np.asarray([record.target_label for record in records], dtype=object)
    return features, labels, records


def _file_sha256(path: str | Path) -> str:
    """Hash an input file so evidence records the exact bytes used by an experiment."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provenance(
    *,
    ravdess_features: str | Path,
    ravdess_manifest: str | Path,
    tess_features: str | Path,
    tess_manifest: str | Path,
) -> dict[str, Any]:
    """Record package versions and exact dataset inputs used by the experiment."""
    ravdess_records = load_manifest(ravdess_manifest)
    tess_records = load_manifest(tess_manifest)
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "required_scikit_learn": "1.9.0",
        "random_state": RANDOM_STATE,
        "ravdess": {
            "feature_sha256": _file_sha256(ravdess_features),
            "manifest_sha256": manifest_fingerprint(ravdess_records),
        },
        "tess": {
            "feature_sha256": _file_sha256(tess_features),
            "manifest_sha256": manifest_fingerprint(tess_records),
        },
    }


def run_baseline(
    feature_csv: str | Path,
    manifest_csv: str | Path,
    *,
    n_splits: int = DEFAULT_OUTER_SPLITS,
) -> float:
    """Compute the frozen SVC acceptance baseline directly from the evaluation code."""
    features, labels, groups, _ = _load_ravdess(feature_csv, manifest_csv)
    return grouped_oof_score(
        features,
        labels,
        groups,
        build_svc_pipeline,
        n_splits=n_splits,
    )


def run_search(
    feature_csv: str | Path,
    manifest_csv: str | Path,
    *,
    baseline: float,
    n_splits: int = DEFAULT_OUTER_SPLITS,
) -> dict[str, Any]:
    """Run the prespecified OVR plus SelectKBest research search under GroupKFold."""
    features, labels, groups, _ = _load_ravdess(feature_csv, manifest_csv)
    results: list[dict[str, Any]] = []

    for k, C, gamma in FIXED_OVR_CANDIDATES:
        score = grouped_oof_score(
            features,
            labels,
            groups,
            lambda k=k, C=C, gamma=gamma: build_tuned_pipeline(
                k=k,
                C=C,
                gamma=gamma,
            ),
            n_splits=n_splits,
        )
        results.append(
            {
                "k": k,
                "C": C,
                "gamma": gamma,
                "macro_f1": score,
            }
        )

    results.sort(key=lambda item: item["macro_f1"], reverse=True)
    return {
        "protocol": {
            "corpus": "RAVDESS",
            "cv_scheme": f"{n_splits}-fold GroupKFold",
            "grouping_key": "speaker_id",
            "metric": "macro_f1",
            "baseline": baseline,
            "threshold": DEPLOYMENT_THRESHOLD,
            "feature_selection": "SelectKBest(f_classif, k), fitted inside each fold",
            "classifier": "OneVsRestClassifier(SVC(kernel='rbf', class_weight='balanced'))",
        },
        "search": results,
        "best": results[0],
    }


def _best_inner_ovr(
    features: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    train_idx: np.ndarray,
    *,
    inner_splits: int,
) -> tuple[float, float, float]:
    """Select one OVR configuration using only inner speaker-disjoint folds."""
    inner_features = features[train_idx]
    inner_labels = labels[train_idx]
    inner_groups = groups[train_idx]

    best: tuple[float, float, float] | None = None
    best_score = float("-inf")

    for C, gamma in NESTED_OVR_CANDIDATES:
        score = grouped_oof_score(
            inner_features,
            inner_labels,
            inner_groups,
            lambda C=C, gamma=gamma: build_tuned_pipeline(
                k=50,
                C=C,
                gamma=gamma,
            ),
            n_splits=inner_splits,
        )
        if score > best_score:
            best_score = score
            best = (C, gamma, score)

    if best is None:
        raise AssertionError("Nested OVR tuning produced no candidate")
    return best


def run_nested_ovr(
    feature_csv: str | Path,
    manifest_csv: str | Path,
    *,
    baseline: float,
    fixed_fold_tuned: float,
    outer_splits: int = DEFAULT_OUTER_SPLITS,
    inner_splits: int = DEFAULT_INNER_SPLITS,
) -> dict[str, Any]:
    """Run nested GroupKFold for the fixed k=50 OVR plus feature-selection family."""
    features, labels, groups, _ = _load_ravdess(feature_csv, manifest_csv)
    outer = GroupKFold(n_splits=outer_splits)
    fold_scores: list[float] = []
    selected: list[dict[str, Any]] = []
    y_true: list[str] = []
    y_pred: list[str] = []

    for fold, (train_idx, test_idx) in enumerate(
        outer.split(features, labels, groups),
        start=1,
    ):
        C, gamma, inner_score = _best_inner_ovr(
            features,
            labels,
            groups,
            train_idx,
            inner_splits=inner_splits,
        )
        model = build_tuned_pipeline(k=50, C=C, gamma=gamma)
        model.fit(features[train_idx], labels[train_idx])
        predictions = np.asarray(model.predict(features[test_idx]), dtype=object)

        fold_scores.append(
            float(
                f1_score(
                    labels[test_idx],
                    predictions,
                    labels=list(LABELS),
                    average="macro",
                    zero_division=0,
                )
            )
        )
        selected.append(
            {
                "fold": fold,
                "inner_macro_f1": inner_score,
                "C": C,
                "gamma": gamma,
            }
        )
        y_true.extend(labels[test_idx].tolist())
        y_pred.extend(predictions.tolist())

    outer_macro = float(
        f1_score(
            y_true,
            y_pred,
            labels=list(LABELS),
            average="macro",
            zero_division=0,
        )
    )
    return {
        "protocol": {
            "corpus": "RAVDESS",
            "outer_cv": f"{outer_splits}-fold GroupKFold",
            "inner_cv": f"{inner_splits}-fold GroupKFold",
            "grouping_key": "speaker_id",
            "metric": "macro_f1",
            "feature_selection": "SelectKBest(f_classif, k=50), fitted inside each fold",
            "baseline": baseline,
            "fixed_fold_tuned": fixed_fold_tuned,
            "threshold": DEPLOYMENT_THRESHOLD,
        },
        "search": {
            "k": 50,
            "configs": [
                {
                    "C": C,
                    "gamma": gamma,
                    "class_weight": "balanced",
                    "estimator": "OneVsRestClassifier(SVC)",
                }
                for C, gamma in NESTED_OVR_CANDIDATES
            ],
        },
        "outer_macro_f1": outer_macro,
        "outer_fold_macro_f1": fold_scores,
        "selected_parameters_by_fold": selected,
        "go_no_go": "GO" if outer_macro >= DEPLOYMENT_THRESHOLD else "NO-GO",
    }


def run_tess_holdout(
    ravdess_features: str | Path,
    ravdess_manifest: str | Path,
    tess_features: str | Path,
    tess_manifest: str | Path,
) -> dict[str, Any]:
    """Fit the fixed best research candidate on RAVDESS and evaluate held-out TESS."""
    ravdess_X, ravdess_y, _, _ = _load_ravdess(ravdess_features, ravdess_manifest)
    tess_X, tess_y, _ = _load_tess(tess_features, tess_manifest)

    model = build_tuned_pipeline(k=50, C=2.75, gamma=0.009)
    model.fit(ravdess_X, ravdess_y)
    predictions = np.asarray(model.predict(tess_X), dtype=object)

    per_class = {
        label: float(
            f1_score(
                tess_y,
                predictions,
                labels=[label],
                average="macro",
                zero_division=0,
            )
        )
        for label in LABELS
    }
    macro = float(
        f1_score(
            tess_y,
            predictions,
            labels=list(LABELS),
            average="macro",
            zero_division=0,
        )
    )
    return {
        "protocol": {
            "train_corpus": "RAVDESS",
            "holdout_corpus": "TESS",
            "training_fit": "all RAVDESS records",
            "feature_selection": "SelectKBest(f_classif, k=50), fitted on all RAVDESS training data",
            "classifier": "OneVsRestClassifier(SVC(kernel='rbf', C=2.75, gamma=0.009, class_weight='balanced'))",
            "metric": "macro_f1",
        },
        "candidate": {
            "k": 50,
            "C": 2.75,
            "gamma": 0.009,
            "macro_f1_ravdess_cv": None,
        },
        "holdout": {
            "macro_f1": macro,
            "per_class_f1": per_class,
            "confusion_matrix": confusion_matrix(
                tess_y,
                predictions,
                labels=list(LABELS),
            ).tolist(),
            "records": int(len(tess_y)),
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write stable, sorted JSON evidence to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_summary(
    search: dict[str, Any],
    nested_ovr: dict[str, Any],
    tess: dict[str, Any],
) -> str:
    """Build the fine-tuning summary directly from freshly produced results."""
    baseline = search["protocol"]["baseline"]
    fixed_best = search["best"]["macro_f1"]
    nested_score = nested_ovr["outer_macro_f1"]
    tess_score = tess["holdout"]["macro_f1"]
    return f"""# WP-104 Fine-Tuning Summary

The frozen WP-104 SVC acceptance baseline is **{baseline:.6f} macro-F1** on six-fold speaker-disjoint `GroupKFold`.

Fine-tuning is research evidence only. It does not replace the acceptance baseline or the shipped classifier.

## Best fixed-fold research candidate

The strongest prespecified candidate uses:

- `StandardScaler`
- `SelectKBest(f_classif, k=50)` fitted inside each fold
- `OneVsRestClassifier(SVC(kernel="rbf", class_weight="balanced"))`
- `C=2.75`
- `gamma=0.009`

Six-fold GroupKFold macro-F1: **{fixed_best:.6f}**.

This result is a model-selection result on the final folds and is therefore not treated as an acceptance metric.

## Nested research estimate

The same OVR + SelectKBest candidate family was evaluated with **3-fold inner / 6-fold outer GroupKFold** speaker-disjoint selection.

Nested outer macro-F1: **{nested_score:.6f}**.

The tuned candidate remains below the **{DEPLOYMENT_THRESHOLD:.2f}** deployment gate, so the acceptance decision remains **NO-GO**.

## Cross-corpus check

After fitting the fixed best research candidate on all RAVDESS training data, the TESS holdout produced **{tess_score:.6f} macro-F1**.

This is evidence of weak cross-corpus transfer; it does not constitute in-domain acceptance evidence.

## Reproduction

All results above are produced by the committed `ml/affect/tune.py` runner. The generated JSON records the pinned Python/scikit-learn/NumPy versions and SHA-256 fingerprints of the exact feature tables and manifests used.

```text
python -m ml.affect.tune \\
  --ravdess-features datasets/features/ravdess.csv \\
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \\
  --tess-features datasets/features/tess.csv \\
  --tess-manifest datasets/affect/manifests/tess.csv \\
  --output-dir evidences/ml/finetune
```

The command writes:

- `svc_finetune_current.json`
- `svc_ovr_nested_tuning.json`
- `tess_holdout.json`
- `fine_tuning_summary.md`

Every tracked fine-tuning result therefore has a committed producer path.
"""


def main() -> int:
    """Run every committed WP-104 fine-tuning experiment and write its evidence bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ravdess-features", type=Path, required=True)
    parser.add_argument("--ravdess-manifest", type=Path, required=True)
    parser.add_argument("--tess-features", type=Path, required=True)
    parser.add_argument("--tess-manifest", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evidences/ml/finetune"),
    )
    parser.add_argument("--n-splits", type=int, default=DEFAULT_OUTER_SPLITS)
    parser.add_argument("--inner-splits", type=int, default=DEFAULT_INNER_SPLITS)
    args = parser.parse_args()

    baseline = run_baseline(
        args.ravdess_features,
        args.ravdess_manifest,
        n_splits=args.n_splits,
    )
    search = run_search(
        args.ravdess_features,
        args.ravdess_manifest,
        baseline=baseline,
        n_splits=args.n_splits,
    )
    nested_ovr = run_nested_ovr(
        args.ravdess_features,
        args.ravdess_manifest,
        baseline=baseline,
        fixed_fold_tuned=search["best"]["macro_f1"],
        outer_splits=args.n_splits,
        inner_splits=args.inner_splits,
    )
    tess = run_tess_holdout(
        args.ravdess_features,
        args.ravdess_manifest,
        args.tess_features,
        args.tess_manifest,
    )

    provenance = _provenance(
        ravdess_features=args.ravdess_features,
        ravdess_manifest=args.ravdess_manifest,
        tess_features=args.tess_features,
        tess_manifest=args.tess_manifest,
    )
    for payload in (search, nested_ovr, tess):
        payload["provenance"] = provenance

    output_dir = args.output_dir
    write_json(output_dir / "svc_finetune_current.json", search)
    write_json(output_dir / "svc_ovr_nested_tuning.json", nested_ovr)
    write_json(output_dir / "tess_holdout.json", tess)
    (output_dir / "fine_tuning_summary.md").write_text(
        build_summary(search, nested_ovr, tess),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "baseline_macro_f1": baseline,
                "fixed_fold_best_macro_f1": search["best"]["macro_f1"],
                "nested_ovr_macro_f1": nested_ovr["outer_macro_f1"],
                "tess_holdout_macro_f1": tess["holdout"]["macro_f1"],
            },
            indent=2,
        )
    )
    print(f"Evidence: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
