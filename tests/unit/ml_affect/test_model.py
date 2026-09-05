from ml.affect.model import build_svc_pipeline


def test_svc_pipeline_has_exact_required_steps():
    """Verify that svc pipeline has exact required steps."""
    model = build_svc_pipeline()
    assert list(model.named_steps) == ["scaler", "classifier"]
    assert model.named_steps["classifier"].kernel == "rbf"
    assert model.named_steps["classifier"].class_weight == "balanced"
