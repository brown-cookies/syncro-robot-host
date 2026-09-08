# WP-104 Final Acceptance Evidence

## Selected model

`StandardScaler -> SVC(kernel="rbf", class_weight="balanced")` is the selected prototype classifier.

The fixed MLP comparison used the same RAVDESS feature table, six-fold speaker-disjoint `GroupKFold`, 88 features, and macro-F1.

| Model | RAVDESS macro-F1 | Threshold | Result |
|---|---:|---:|---|
| SVC (RBF) | 0.632258 | 0.70 | NO-GO |
| MLP (64,) | 0.625254 | 0.70 | NO-GO |

MLP − SVC = **-0.007005**. Therefore SVC remains selected.

## Acceptance

- RAVDESS: 1,440 records / 24 speakers.
- Evaluation: six-fold `GroupKFold`, grouped by `speaker_id`.
- Feature count: 88 eGeMAPSv02 Functionals features.
- Primary metric: macro-F1.
- Deployment gate: **>= 0.70**.
- Selected SVC macro-F1: **0.632258**.
- Decision: **NO-GO**.

The baseline is frozen and will not be replaced by later tuning results. Any attempt to improve the score is recorded as a separate experiment.

## Runtime verification

The documented training command completed successfully from the committed RAVDESS/TESS feature tables and alignment sidecars. A fresh `affect_svc_v1.joblib` was persisted, loaded through `ml.affect.artifacts.load_model_artifact`, and used for sample predictions from the committed RAVDESS feature table.

The verification environment used scikit-learn **1.8.0**; the repository requirement remains pinned to **1.9.0**. The training metadata now records both the required version and the actual runtime version instead of conflating them.

## Evidence

- `evidences/ml/experiment/metrics.json`
- `evidences/ml/experiment/svc_vs_mlp_comparison.json`
- `evidences/ml/experiment/method_note.md`
- `evidences/ml/experiment/ravdess_confusion_matrix.csv`
- `evidences/ml/experiment/tess_confusion_matrix.csv`
- `datasets/features/ravdess.alignment.json`
- `datasets/features/tess.alignment.json`

## Reproduction

```bash
python -m ml.affect.train --ravdess-features datasets/features/ravdess.csv --ravdess-manifest datasets/affect/manifests/ravdess.csv --tess-features datasets/features/tess.csv --tess-manifest datasets/affect/manifests/tess.csv --output models/affect/affect_svc_v1.joblib
```

```bash
python -m ml.affect.compare --ravdess-features datasets/features/ravdess.csv --ravdess-manifest datasets/affect/manifests/ravdess.csv --n-splits 6 --output evidences/ml/experiment/svc_vs_mlp_comparison.json
```
