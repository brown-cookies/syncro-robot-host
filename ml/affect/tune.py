"""Run leakage-safe WP-104 affect classifier fine-tuning experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from .dataset import load_manifest, validate_feature_table

LABELS = ("Low", "Moderate", "High")
RANDOM_STATE = 42


def build_tuned_pipeline(*, k: int = 50, C: float = 2.75, gamma: float = 0.009) -> Pipeline:
    """Build the current best research candidate using fold-fitted feature selection and OVR RBF SVC."""
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("select", SelectKBest(f_classif, k=k)),
            (
                "classifier",
                OneVsRestClassifier(
                    SVC(kernel="rbf", C=C, gamma=gamma, class_weight="balanced")
                ),
            ),
        ]
    )


def grouped_oof_score(features: np.ndarray, labels: np.ndarray, groups: np.ndarray, factory) -> float:
    """Measure macro-F1 with six speaker-disjoint out-of-fold predictions."""
    y_true: list[str] = []
    y_pred: list[str] = []
    splitter = GroupKFold(n_splits=6)
    for train_idx, test_idx in splitter.split(features, labels, groups):
        model = factory()
        model.fit(features[train_idx], labels[train_idx])
        y_true.extend(labels[test_idx].tolist())
        y_pred.extend(np.asarray(model.predict(features[test_idx]), dtype=object).tolist())
    return float(f1_score(y_true, y_pred, labels=list(LABELS), average="macro", zero_division=0))


def run_search(feature_csv: str | Path, manifest_csv: str | Path) -> dict[str, Any]:
    """Search a small predeclared OVR feature-selection/SVC neighborhood under GroupKFold."""
    features = validate_feature_table(feature_csv, manifest_csv)
    records = load_manifest(manifest_csv)
    labels = np.asarray([record.target_label for record in records], dtype=object)
    groups = np.asarray([record.speaker_id for record in records], dtype=object)
    candidates = [
        (45, 2.5, 0.0085),
        (50, 2.5, 0.0085),
        (50, 2.75, 0.009),
        (50, 3.0, 0.0095),
        (55, 2.75, 0.009),
    ]
    results = []
    for k, C, gamma in candidates:
        score = grouped_oof_score(
            features,
            labels,
            groups,
            lambda k=k, C=C, gamma=gamma: build_tuned_pipeline(k=k, C=C, gamma=gamma),
        )
        results.append({"k": k, "C": C, "gamma": gamma, "macro_f1": score})
    results.sort(key=lambda item: item["macro_f1"], reverse=True)
    return {
        "protocol": {
            "corpus": "RAVDESS",
            "cv_scheme": "6-fold GroupKFold",
            "grouping_key": "speaker_id",
            "metric": "macro_f1",
            "baseline": 0.6322582442748598,
            "threshold": 0.70,
            "feature_selection": "SelectKBest(f_classif), fitted inside each fold",
            "classifier": "OneVsRestClassifier(SVC(kernel='rbf', class_weight='balanced'))",
        },
        "search": results,
        "best": results[0],
    }


def main() -> int:
    """Run the reproducible fine-tuning search and write JSON evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ravdess-features", type=Path, required=True)
    parser.add_argument("--ravdess-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evidences/ml/finetune/svc_finetune_current.json"))
    args = parser.parse_args()
    result = run_search(args.ravdess_features, args.ravdess_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["best"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
