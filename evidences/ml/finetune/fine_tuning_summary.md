# WP-104 Fine-Tuning Summary

The frozen WP-104 SVC acceptance baseline is **0.632258 macro-F1** on six-fold speaker-disjoint `GroupKFold`.

Fine-tuning is research evidence only. It does not replace the acceptance baseline or the shipped classifier.

## Best fixed-fold research candidate

The strongest prespecified candidate uses:

- `StandardScaler`
- `SelectKBest(f_classif, k=50)` fitted inside each fold
- `OneVsRestClassifier(SVC(kernel="rbf", class_weight="balanced"))`
- `C=2.75`
- `gamma=0.009`

Six-fold GroupKFold macro-F1: **0.651618**.

This result is a model-selection result on the final folds and is therefore not treated as an acceptance metric.

## Nested research estimate

The same OVR + SelectKBest candidate family was evaluated with **3-fold inner / 6-fold outer GroupKFold** speaker-disjoint selection.

Nested outer macro-F1: **0.650564**.

The tuned candidate remains below the **0.70** deployment gate, so the acceptance decision remains **NO-GO**.

## Cross-corpus check

After fitting the fixed best research candidate on all RAVDESS training data, the TESS holdout produced **0.240470 macro-F1**.

This is evidence of weak cross-corpus transfer; it does not constitute in-domain acceptance evidence.

## Reproduction

All results above are produced by the committed `ml/affect/tune.py` runner. The generated JSON records the pinned Python/scikit-learn/NumPy versions and SHA-256 fingerprints of the exact feature tables and manifests used.

```text
python -m ml.affect.tune \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --tess-features datasets/features/tess.csv \
  --tess-manifest datasets/affect/manifests/tess.csv \
  --output-dir evidences/ml/finetune
```

The command writes:

- `svc_finetune_current.json`
- `svc_ovr_nested_tuning.json`
- `tess_holdout.json`
- `fine_tuning_summary.md`

Every tracked fine-tuning result therefore has a committed producer path.
