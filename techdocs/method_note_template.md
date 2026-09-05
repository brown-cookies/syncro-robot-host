# WP-104 Affect Classifier Method Note

## 1. Dataset

- RAVDESS: 1,440 clips / 24 speakers; primary GroupKFold corpus.
- TESS: 2,800 clips / 2 speakers; held-out generalisation check only.
- Audio normalization: 16 kHz, mono.

## 2. Label mapping

See `ml/affect/label_mapping.md`.

## 3. Feature extraction

- openSMILE version: `2.6.0`
- Feature set: `eGeMAPSv02`
- Feature level: `Functionals`
- Feature count: 88

## 4. Classifier

- Shipped default: SVC
- Pipeline: `StandardScaler -> SVC(kernel="rbf", class_weight="balanced")`
- Random seed: `42`
- scikit-learn version: `<record actual pinned version>`
- joblib version: `<record actual pinned version>`

MLPClassifier comparison status: `<not run / run and result>`.

## 5. Evaluation

- Cross-validation: `GroupKFold`
- Number of folds: `<k>`
- Grouping key: `speaker_id`
- Leakage check: `<result>`
- RAVDESS macro-F1: `<value>`
- Low F1: `<value>`
- Moderate F1: `<value>`
- High F1: `<value>`
- TESS held-out result: `<value(s)>`

## 6. Go / no-go

Threshold: **macro-F1 >= 0.70**.

Measured outcome: `<GO / NO-GO>`.

If below threshold, scope-down statement: report the measured result and retain the classifier as
the best available measured prototype signal; do not describe it as a validated clinical stress detector.

## 7. Runtime artifact

- Artifact: `models/affect/affect_svc_v1.joblib`
- Metadata sidecar: `models/affect/affect_svc_v1.joblib.json`
- Runtime adapter: `adapters/affect/classifier_detector.py`
- Latency logging: `<feature extraction / inference / total>`
