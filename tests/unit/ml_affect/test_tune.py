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

# The macro-F1 values recorded below are only reproducible on the exact pinned scikit-learn
# release: cross-version drift (observed ~4.4e-3 on 1.6.1 vs 1.9.0) is larger than any tolerance
# we could widen to without also accepting a genuinely different, unpinned result. Skip on any
# other version rather than loosen the assertions, per requirements.txt's scikit-learn==1.9.0 pin.
REQUIRED_SCIKIT_LEARN_VERSION = "1.9.0"
requires_pinned_sklearn = pytest.mark.skipif(
    sklearn.__version__ != REQUIRED_SCIKIT_LEARN_VERSION,
    reason=(
        "Recorded macro-F1 values only reproduce on the pinned "
        f"scikit-learn=={REQUIRED_SCIKIT_LEARN_VERSION}; found {sklearn.__version__}."
    ),
)


@pytest.mark.ml
@requires_pinned_sklearn
def test_finetune_search_reproduces_recorded_baseline_and_candidate() -> None:
    baseline = run_baseline(RAVDESS_FEATURES, RAVDESS_MANIFEST)
    result = run_search(
        RAVDESS_FEATURES,
        RAVDESS_MANIFEST,
        baseline=baseline,
    )

    assert baseline == pytest.approx(0.6322582442748598, rel=1e-5, abs=1e-6)
    assert result["best"]["macro_f1"] == pytest.approx(0.6516183148186734, rel=1e-5, abs=1e-6)
    assert result["best"]["k"] == 50
    assert result["best"]["C"] == pytest.approx(2.75)
    assert result["best"]["gamma"] == pytest.approx(0.009)


@pytest.mark.ml
@requires_pinned_sklearn
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

    assert result["outer_macro_f1"] == pytest.approx(0.6505641026555925, rel=1e-5, abs=1e-6)
    assert len(result["selected_parameters_by_fold"]) == 6
    assert result["go_no_go"] == "NO-GO"


@pytest.mark.ml
@requires_pinned_sklearn
def test_tess_holdout_reproduces_recorded_cross_corpus_result() -> None:
    result = run_tess_holdout(
        RAVDESS_FEATURES,
        RAVDESS_MANIFEST,
        TESS_FEATURES,
        TESS_MANIFEST,
    )

    assert result["holdout"]["macro_f1"] == pytest.approx(0.24046961160239735, rel=1e-5, abs=1e-6)
    assert result["holdout"]["per_class_f1"]["Moderate"] == pytest.approx(
        0.008038585209003215, rel=1e-4, abs=1e-6
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
        assert isinstance(payload["provenance"]["scikit_learn"], str)
        assert payload["provenance"]["scikit_learn"]
        assert payload["provenance"]["required_scikit_learn"] == "1.9.0"
        assert payload["provenance"]["random_state"] == 42
