"""WP-104 classifier construction."""

from __future__ import annotations

from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

RANDOM_STATE = 42


def build_svc_pipeline() -> Pipeline:
    """Build the fixed affect classifier pipeline using StandardScaler and RBF SVC."""
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "classifier",
                SVC(kernel="rbf", class_weight="balanced", random_state=RANDOM_STATE),
            ),
        ]
    )
