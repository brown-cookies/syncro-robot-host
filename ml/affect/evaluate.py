"""Speaker-independent evaluation and held-out scoring for WP-104."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, cast

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold

from .dataset import load_manifest, validate_feature_table
from .model import build_svc_pipeline

ALLOWED_LEVELS = ("Low", "Moderate", "High")
DEFAULT_N_SPLITS = 6
DEPLOYMENT_THRESHOLD = 0.70


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Capture aggregate classification metrics and predictions for one evaluation."""

    macro_f1: float
    per_class_f1: dict[str, float]
    confusion_matrix: np.ndarray
    y_true: tuple[str, ...]
    y_pred: tuple[str, ...]
    n_splits: int | None


def evaluate_predictions(
    y_true: list[str] | np.ndarray,
    y_pred: list[str] | np.ndarray,
    *,
    n_splits: int | None,
) -> EvaluationResult:
    """Calculate fixed WP-104 macro-F1, per-class F1, and a 3x3 confusion matrix."""
    true_values = [str(value)
                   for value in np.asarray(y_true, dtype=object).tolist()]
    pred_values = [str(value)
                   for value in np.asarray(y_pred, dtype=object).tolist()]
    if len(true_values) != len(pred_values):
        raise ValueError(
            "Evaluation labels and predictions must have equal lengths")
    if not true_values:
        raise ValueError("Evaluation requires at least one prediction")
    labels = list(ALLOWED_LEVELS)
    unexpected = (set(true_values) | set(pred_values)) - set(labels)
    if unexpected:
        raise ValueError(
            f"Evaluation contains invalid affect levels: {sorted(unexpected)}")

    macro = float(
        f1_score(
            true_values,
            pred_values,
            labels=labels,
            average="macro",
            zero_division=0,
        )
    )
    report = cast(
        dict[str, Any],
        classification_report(
            true_values,
            pred_values,
            labels=labels,
            target_names=labels,
            output_dict=True,
            zero_division=0,
        ),
    )
    per_class = {label: float(report[label]["f1-score"]) for label in labels}
    matrix = confusion_matrix(true_values, pred_values, labels=labels)
    if matrix.shape != (3, 3):
        raise AssertionError("WP-104 confusion matrix must always be 3x3")
    return EvaluationResult(
        macro_f1=macro,
        per_class_f1=per_class,
        confusion_matrix=matrix,
        y_true=tuple(true_values),
        y_pred=tuple(pred_values),
        n_splits=n_splits,
    )


def evaluate_ravdess(
    features: np.ndarray,
    manifest_csv: str | Path,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
    model_factory: Callable[[], Any] | None = None,
) -> EvaluationResult:
    """Evaluate RAVDESS using speaker-grouped cross-validation and OOF predictions."""
    records = load_manifest(manifest_csv)
    if model_factory is None:
        model_factory = build_svc_pipeline
    if any(record.corpus != "ravdess" for record in records):
        raise ValueError(
            "RAVDESS GroupKFold manifest must contain RAVDESS records only")
    features = _validate_matrix(features, len(records), "RAVDESS")
    speakers = {record.speaker_id for record in records}
    if n_splits > len(speakers):
        raise ValueError(
            "n_splits cannot exceed the number of distinct RAVDESS speakers")

    y = np.asarray([record.target_label for record in records], dtype=object)
    groups = np.asarray(
        [record.speaker_id for record in records], dtype=object)
    splitter = GroupKFold(n_splits=n_splits)
    y_true: list[str] = []
    y_pred: list[str] = []

    for fold_number, (train_idx, test_idx) in enumerate(
        splitter.split(features, y, groups=groups),
        start=1,
    ):
        train_speakers = set(groups[train_idx])
        test_speakers = set(groups[test_idx])
        if train_speakers & test_speakers:
            raise AssertionError(
                f"Speaker leakage detected in GroupKFold fold {fold_number}"
            )
        model = model_factory()
        model.fit(features[train_idx], y[train_idx])
        predictions = model.predict(features[test_idx])
        y_true.extend(y[test_idx].tolist())
        y_pred.extend(np.asarray(predictions, dtype=object).tolist())

    result = evaluate_predictions(y_true, y_pred, n_splits=n_splits)
    if len(result.y_true) != len(records):
        raise AssertionError(
            "OOF predictions do not cover every RAVDESS record")
    return result


def evaluate_held_out(
    model: Any,
    features: np.ndarray,
    manifest_csv: str | Path,
    *,
    corpus: str = "tess",
) -> EvaluationResult:
    """Evaluate a frozen trained classifier on an external held-out corpus."""
    records = load_manifest(manifest_csv)
    expected_corpus = corpus.strip().lower()
    if expected_corpus not in {"ravdess", "tess"}:
        raise ValueError(f"Unsupported held-out corpus: {corpus!r}")
    if any(record.corpus != expected_corpus for record in records):
        raise ValueError(
            f"Manifest contains a corpus other than {expected_corpus!r}")
    features = _validate_matrix(
        features, len(records), expected_corpus.upper())
    predictions = model.predict(features)
    return evaluate_predictions(
        [record.target_label for record in records],
        np.asarray(predictions, dtype=object),
        n_splits=None,
    )


def _validate_matrix(features: np.ndarray, record_count: int, corpus: str) -> np.ndarray:
    """Validate an in-memory feature matrix at the evaluation boundary."""
    matrix = np.asarray(features, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != 88:
        raise ValueError(
            f"{corpus} evaluation features must have exactly 88 columns")
    if matrix.shape[0] != record_count:
        raise ValueError(
            f"{corpus} feature rows ({matrix.shape[0]}) != manifest rows ({record_count})"
        )
    if not np.isfinite(matrix).all():
        raise ValueError(
            f"{corpus} evaluation features must contain only finite values")
    return matrix


def format_metrics(result: EvaluationResult) -> str:
    """Render stable human-readable metrics for WP-104 evidence and CLI output."""
    lines = [f"macro-F1: {result.macro_f1:.6f}"]
    lines.extend(
        f"{label} F1: {result.per_class_f1[label]:.6f}" for label in ALLOWED_LEVELS
    )
    lines.append("confusion matrix [Low, Moderate, High]:")
    lines.extend("  " + " ".join(str(int(value)) for value in row)
                 for row in result.confusion_matrix)
    return "\n".join(lines)


def load_and_evaluate_ravdess(
    feature_csv: str | Path,
    manifest_csv: str | Path,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
) -> EvaluationResult:
    """Load validated RAVDESS features and produce speaker-independent OOF metrics."""
    return evaluate_ravdess(
        validate_feature_table(feature_csv, manifest_csv),
        manifest_csv,
        n_splits=n_splits,
    )
