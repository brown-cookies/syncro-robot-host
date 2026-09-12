"""Versioned model artifact persistence for WP-104."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import joblib
import sklearn

ARTIFACT_VERSION = "affect_svc_v1"


def save_model_artifact(model: Any, path: str | Path, *, extra_metadata: dict[str, Any] | None = None) -> Path:
    """Persist a trained affect model artifact with its metadata."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, target)
    metadata = {
        "artifact_version": ARTIFACT_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scikit_learn_version": sklearn.__version__,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    metadata_path = target.with_suffix(target.suffix + ".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_model_artifact(path: str | Path):
    """Load a persisted affect model artifact for runtime inference."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Affect model artifact not found: {target}")
    try:
        return joblib.load(target)
    except Exception as exc:
        raise RuntimeError(f"Could not load affect model artifact: {target}") from exc


def read_artifact_metadata(path: str | Path) -> dict[str, Any]:
    """Read metadata associated with a persisted affect model artifact."""
    metadata_path = Path(path).with_suffix(Path(path).suffix + ".json")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Affect model metadata not found: {metadata_path}")
    return json.loads(metadata_path.read_text(encoding="utf-8"))
