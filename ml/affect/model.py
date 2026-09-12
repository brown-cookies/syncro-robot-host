"""WP-104 affect classifier construction."""

from __future__ import annotations

from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

RANDOM_STATE = 42
MLP_HIDDEN_LAYER_SIZES = (64,)
MLP_MAX_ITER = 1000
MLP_ALPHA = 1e-4
MLP_LEARNING_RATE_INIT = 1e-3


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


def build_mlp_pipeline() -> Pipeline:
    """Build the prespecified shallow MLP comparison pipeline with standardized features."""
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "classifier",
                MLPClassifier(
                    hidden_layer_sizes=MLP_HIDDEN_LAYER_SIZES,
                    activation="relu",
                    solver="adam",
                    alpha=MLP_ALPHA,
                    learning_rate_init=MLP_LEARNING_RATE_INIT,
                    max_iter=MLP_MAX_ITER,
                    random_state=RANDOM_STATE,
                    early_stopping=False,
                ),
            ),
        ]
    )
