from __future__ import annotations

import json
from pathlib import Path

import pytest
import sklearn

from ml.affect.tune import run_baseline, run_search, run_nested_ovr, run_tess_holdout


ROOT = Path(__file__).resolve().parents[3]
RAVDESS_FEATURES = ROOT / "datasets/features/ravdess.csv"
RAVDESS_MANIFEST = ROOT / "datasets/affect/manifests/ravdess.csv"
TESS_FEATURES = ROOT / "datasets/features/tess.csv"
TESS_MANIFEST = ROOT / "datasets/affect/manifests/tess.csv"


@pytest.mark.ml
def test_finetune_search_reproduces_recorded_baseline_and_candidate() -> None:
    baseline = run_baseline(RAVDESS_FEATURES, RAVDESS_MANIFEST)
    result = run_search(
        RAVDESS_FEATURES,
        RAVDESS_MANIFEST,
        baseline=baseline,
    )

    assert baseline == pytest.approx(0.6322582442748598)
    assert result["best"]["macro_f1"] == pytest.approx(0.6516183148186734)
    assert result["best"]["k"] == 50
    assert result["best"]["C"] == pytest.approx(2.75)
    assert result["best"]["gamma"] == pytest.approx(0.009)


@pytest.mark.ml
def test_nested_ovr_reproduces_recorded_candidate() -> None:
    baseline = run_baseline(RAVDESS_FEATURES, RAVDESS_MANIFEST)
    fixed = run_search(
        RAVDESS_FEATURES,
        RAVDESS_MANIFEST,
        baseline=baseline,
    )
    result = run_nested_ovr(
        RAVDESS_FEATURES,
        RAVDESS_MANIFEST,
        baseline=baseline,
        fixed_fold_tuned=fixed["best"]["macro_f1"],
    )

    assert result["outer_macro_f1"] == pytest.approx(0.6505641026555925)
    assert len(result["selected_parameters_by_fold"]) == 6
    assert result["go_no_go"] == "NO-GO"


@pytest.mark.ml
def test_tess_holdout_reproduces_recorded_cross_corpus_result() -> None:
    result = run_tess_holdout(
        RAVDESS_FEATURES,
        RAVDESS_MANIFEST,
        TESS_FEATURES,
        TESS_MANIFEST,
    )

    assert result["holdout"]["macro_f1"] == pytest.approx(0.24046961160239735)
    assert result["holdout"]["per_class_f1"]["Moderate"] == pytest.approx(
        0.008038585209003215
    )


@pytest.mark.ml
def test_finetune_evidence_has_a_committed_producer_schema() -> None:
    evidence_dir = ROOT / "evidences/ml/finetune"
    expected = {
        "svc_finetune_current.json",
        "svc_ovr_nested_tuning.json",
        "tess_holdout.json",
    }
    actual = {path.name for path in evidence_dir.glob("*.json")}
    assert actual == expected

    for filename in expected:
        payload = json.loads((evidence_dir / filename).read_text(encoding="utf-8"))
        assert "provenance" in payload
        assert payload["provenance"]["scikit_learn"] == sklearn.__version__
        assert payload["provenance"]["random_state"] == 42
