"""Training entry point for the WP-104 fixed SVC pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from .artifacts import save_model_artifact
from .dataset import load_manifest, validate_feature_table
from .model import RANDOM_STATE, build_svc_pipeline


def train_from_features(feature_csv: str | Path, manifest_csv: str | Path, output_path: str | Path):
    """Fit the fixed affect classifier from aligned feature data and labels."""
    features = validate_feature_table(feature_csv, manifest_csv)
    records = load_manifest(manifest_csv)
    model = build_svc_pipeline()
    model.fit(features, [record.target_label for record in records])
    save_model_artifact(model, output_path, extra_metadata={"random_state": RANDOM_STATE})
    return model


def main() -> int:
    """Run the command-line entry point for this module."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("models/affect/affect_svc_v1.joblib"))
    args = parser.parse_args()
    train_from_features(args.features, args.manifest, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
