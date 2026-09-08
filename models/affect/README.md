# WP-104 runtime artifacts

The trained classifier artifact is intentionally not committed because it is a generated binary.

Generate it locally with:

```bash
python -m ml.affect.train \
  --ravdess-features datasets/features/ravdess.csv \
  --ravdess-manifest datasets/affect/manifests/ravdess.csv \
  --tess-features datasets/features/tess.csv \
  --tess-manifest datasets/affect/manifests/tess.csv \
  --output models/affect/affect_svc_v1.joblib
```

The command also writes the artifact metadata sidecar at `models/affect/affect_svc_v1.joblib.json`.
