# WP-104 Affect Classifier Method Note

## Dataset

- RAVDESS: 1,440 clips / 24 speakers; primary evaluation corpus.
- TESS: 2,800 clips / 2 speakers; held-out generalisation check only.
- Audio normalization: 16 kHz, mono.
- Feature table: exactly 88 eGeMAPSv02 Functionals features.
- Label mapping: see `techdocs/label_mapping.md`.

## Classifier

- Pipeline: `StandardScaler -> SVC(kernel=\"rbf\", class_weight=\"balanced\")`.
- Random state: 42.
- Training environment used for the final verification: scikit-learn 1.8.0; repository requirement remains pinned to 1.9.0 for reproducible deployment environments.
- joblib used for this run: 1.6.0.
- Shipped artifact: `models/affect/affect_svc_v1.joblib`.
- Artifact version: `affect_svc_v1`.
- MLPClassifier comparison: completed on the identical six-fold RAVDESS GroupKFold protocol; SVC remains the fixed prototype classifier.

## RAVDESS Evaluation

- Scheme: `GroupKFold`.
- Folds: 6.
- Grouping key: `speaker_id`.
- Leakage check: no speaker appeared in both train and validation sides of any fold.
- Macro-F1: **0.632258**.
- Per-class F1:
- Low: 0.652666
- Moderate: 0.474359
- High: 0.769750

## SVC vs MLP Comparison

- Protocol: identical 6-fold `GroupKFold` grouped by `speaker_id`; no speaker overlap between train and validation partitions.
- SVC: `StandardScaler -> SVC(kernel="rbf", class_weight="balanced")`.
- MLP: `StandardScaler -> MLPClassifier(hidden_layer_sizes=(64,), activation="relu", solver="adam", alpha=1e-4, learning_rate_init=1e-3, max_iter=1000, random_state=42, early_stopping=False)`.
- SVC macro-F1: **0.632258**.
- MLP macro-F1: **0.625254**.
- Difference (MLP - SVC): **-0.007005**.
- Comparison result: **SVC wins** and remains the prototype classifier.
- Deployment gate: both results are **NO-GO** at macro-F1 0.70.
- Full comparison evidence: `evidences/ml/svc_vs_mlp_comparison.json`.

### Confusion matrix

Class order: `Low, Moderate, High`. See `ravdess_confusion_matrix.csv`.

```text
macro-F1: 0.632258
Low F1: 0.652666
Moderate F1: 0.474359
High F1: 0.769750
confusion matrix [Low, Moderate, High]:
  202 63 23
  79 185 120
  50 148 570
```

## TESS Held-Out Evaluation

- TESS was not included in RAVDESS GroupKFold.
- Macro-F1: **0.199983**.
- Per-class F1:
- Low: 0.000000
- Moderate: 0.000000
- High: 0.599950

### Confusion matrix

Class order: `Low, Moderate, High`. See `tess_confusion_matrix.csv`.

```text
macro-F1: 0.199983
Low F1: 0.000000
Moderate F1: 0.000000
High F1: 0.599950
confusion matrix [Low, Moderate, High]:
  0 0 400
  2 0 1198
  1 0 1199
```

## Go / No-Go

Threshold: **macro-F1 >= 0.70**.

Measured outcome: **NO-GO**.

The measured macro-F1 is below 0.70; report the classifier as the best measured prototype signal and do not describe it as a validated clinical stress detector.

## Reproduction

The committed feature tables and alignment sidecars can be retrained with `python -m ml.affect.train` using the command documented in `README.md`. The binary artifact is intentionally not committed; `models/affect/README.md` documents its regeneration.
