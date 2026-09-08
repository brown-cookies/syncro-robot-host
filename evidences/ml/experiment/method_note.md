# WP-104 Affect Classifier Method Note

## 1. Dataset

- RAVDESS: 1,440 clips / 24 speakers; primary GroupKFold corpus.
- TESS: 2,800 clips / 2 speakers; held-out generalisation check only.
- Audio normalization: 16 kHz, mono.

## 2. Label mapping

See `techdocs/label_mapping.md`.

## 3. Feature extraction

- openSMILE version: `2.6.0`
- Feature set: `eGeMAPSv02`
- Feature level: `Functionals`
- Feature count: 88

## 4. Classifier

- Shipped default: SVC
- Pipeline: `StandardScaler -> SVC(kernel="rbf", class_weight="balanced")`
- Random seed: `42`
- scikit-learn version: `1.8.0`
- joblib version: `1.5.3`

MLPClassifier comparison status: `run; SVC 0.632258 vs MLP 0.625254 on the identical six-fold GroupKFold protocol; SVC remains selected`.

## 5. Evaluation

- Cross-validation: `GroupKFold`
- Number of folds: `6`
- Grouping key: `speaker_id`
- Leakage check: `no speaker appeared in both train and validation sides of any fold`
- RAVDESS macro-F1: `0.632258`
- Low F1: `0.652666`
- Moderate F1: `0.474359`
- High F1: `0.769750`
- TESS held-out result: `0.199983 macro-F1`

## 6. Go / no-go

Threshold: **macro-F1 >= 0.70**.

Measured outcome: `NO-GO`.

If below threshold, scope-down statement: report the measured result and retain the classifier as
the best available measured prototype signal; do not describe it as a validated clinical stress detector.

## 7. Runtime artifact

- Artifact: `models/affect/affect_svc_v1.joblib`
- Metadata sidecar: `models/affect/affect_svc_v1.joblib.json`
- Runtime adapter: `adapters/affect/classifier_detector.py`
- Latency logging: `feature extraction and classifier inference are measured separately by the runtime adapter`
