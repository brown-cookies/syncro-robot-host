import numpy as np

from ml.affect.artifacts import load_model_artifact, read_artifact_metadata, save_model_artifact
from ml.affect.model import build_svc_pipeline


def test_model_artifact_round_trip(tmp_path):
    """Verify that model artifact round trip."""
    x = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
    y = np.array(["Low", "Low", "High", "High"])
    model = build_svc_pipeline().fit(x, y)
    path = tmp_path / "affect_svc_v1.joblib"
    save_model_artifact(model, path)
    loaded = load_model_artifact(path)
    assert loaded.predict(x).tolist() == model.predict(x).tolist()
    assert read_artifact_metadata(path)["artifact_version"] == "affect_svc_v1"
