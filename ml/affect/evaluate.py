"""Speaker-independent WP-104 evaluation using GroupKFold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold

from .dataset import load_manifest
from .model import build_svc_pipeline, RANDOM_STATE

ALLOWED_LEVELS = ("Low", "Moderate", "High")
DEFAULT_N_SPLITS = 6
DEPLOYMENT_THRESHOLD = 0.70


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    macro_f1: float
    per_class_f1: dict[str, float]
    confusion_matrix: np.ndarray
    y_true: tuple[str, ...]
    y_pred: tuple[str, ...]
    n_splits: int


def evaluate_ravdess(
    features: np.ndarray,
    manifest_csv: str | Path,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
) -> EvaluationResult:
    """Evaluate the affect classifier on RAVDESS using speaker-grouped cross-validation."""
    records = load_manifest(manifest_csv)
    if any(record.corpus.strip().lower() != "ravdess" for record in records):
        raise ValueError("RAVDESS GroupKFold manifest must contain RAVDESS records only")
    if len(records) != len(features):
        raise ValueError(f"Feature rows ({len(features)}) != manifest rows ({len(records)})")
    if len({record.speaker_id for record in records}) < n_splits:
        raise ValueError("n_splits cannot exceed the number of distinct RAVDESS speakers")

    y = np.array([record.target_label for record in records], dtype=object)
    groups = np.array([record.speaker_id for record in records], dtype=object)
    splitter = GroupKFold(n_splits=n_splits)
    y_true: list[str] = []
    y_pred: list[str] = []

    for train_idx, test_idx in splitter.split(features, y, groups=groups):
        train_speakers = set(groups[train_idx])
        test_speakers = set(groups[test_idx])
        if train_speakers & test_speakers:
            raise AssertionError("Speaker leakage detected in GroupKFold split")
        model = build_svc_pipeline()
        model.fit(features[train_idx], y[train_idx])
        predictions = model.predict(features[test_idx])
        y_true.extend(y[test_idx].tolist())
        y_pred.extend(predictions.tolist())

    labels = list(ALLOWED_LEVELS)
    macro = float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))
    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=labels,
        output_dict=True,
        zero_division=0,
    )
    per_class = {label: float(report[label]["f1-score"]) for label in labels}
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    return EvaluationResult(
        macro_f1=macro,
        per_class_f1=per_class,
        confusion_matrix=matrix,
        y_true=tuple(y_true),
        y_pred=tuple(y_pred),
        n_splits=n_splits,
    )
