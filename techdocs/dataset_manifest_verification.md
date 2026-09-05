# WP-104 Dataset Manifest Verification

The repository stores only canonical manifests under `datasets/affect/manifests/`. Raw RAVDESS and
TESS audio remains external/local and is excluded from version control.

Run verification after building the manifests:

```powershell
python -m scripts.verify_affect_manifests
```

To verify the manifest rows against the local audio trees as well:

```powershell
python -m scripts.verify_affect_manifests `
  --ravdess-root datasets/affect/RAVDESS `
  --tess-root datasets/affect/TESS
```

The verifier enforces the WP-104 contract:

- RAVDESS: exactly 1,440 records, 24 speakers, and the eight fixed source labels.
- TESS: exactly 2,800 records, 2 speakers, and the seven fixed source labels.
- Each row has the exact canonical five-column schema.
- Corpus, speaker ID, relative WAV path, source label, and target label are non-empty.
- Source labels map to the fixed `{Low, Moderate, High}` taxonomy.
- Target labels must equal the frozen corpus-specific mapping.
- Audio paths must be relative `.wav` paths and must be unique within a manifest.
- RAVDESS and TESS are verified independently; TESS is never pooled into RAVDESS `GroupKFold`.
