# WP-104 Fine-Tuning Summary

The original WP-104 SVC result remains the acceptance baseline: **0.632258 macro-F1** on six-fold speaker-disjoint `GroupKFold`.

Fine-tuning was run as separate research evidence so the acceptance result cannot be silently replaced.

## Best candidate

The strongest completed candidate used:

- `StandardScaler`
- `SelectKBest(f_classif, k=50)` fitted inside each training fold
- `OneVsRestClassifier(SVC(kernel="rbf", class_weight="balanced"))`
- `C=2.75`
- `gamma=0.009`

Six-fold GroupKFold macro-F1: **0.651618**.

A nested three-fold-inner / six-fold-outer GroupKFold estimate for the same candidate family produced **0.650564** macro-F1.

The improvement over the frozen SVC baseline is therefore approximately **+0.0183 macro-F1** on the nested estimate, but both remain below the **0.70** deployment threshold.

## Held-out check

After fitting the candidate on all RAVDESS data, the fixed TESS holdout produced **0.240470 macro-F1**. This is a major cross-corpus generalisation weakness and is a reason not to promote the tuned candidate as the deployed classifier.

## Decision

**Selected shipped model: unchanged baseline SVC.**

The tuned OVR+feature-selection pipeline remains a research candidate until a subsequent experiment improves both speaker-independent RAVDESS performance and cross-corpus robustness without compromising the stated methodology.

## Reproduction

```text
python -m ml.affect.tune \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --output evidences/ml/finetune/svc_finetune_current.json
```
