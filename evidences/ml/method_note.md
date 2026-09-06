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
- scikit-learn used for this run: 1.9.0.
- joblib used for this run: 1.6.0.
- Shipped artifact: `models\affect\affect_svc_v1.joblib`.
- Artifact version: `affect_svc_v1`.
- MLPClassifier comparison: not run; SVC is the fixed shipped classifier.

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
