"""WP-104 offline affect-model development package.

This package is training/evaluation-only. Runtime code must consume a persisted
artifact through ``adapters.affect.classifier_detector`` instead of importing
training modules.
"""

from .label_mapping import ALLOWED_LEVELS, RAVDESS_LABEL_MAP, TESS_LABEL_MAP, map_label
from .model import build_svc_pipeline

__all__ = [
    "ALLOWED_LEVELS",
    "RAVDESS_LABEL_MAP",
    "TESS_LABEL_MAP",
    "map_label",
    "build_svc_pipeline",
]
