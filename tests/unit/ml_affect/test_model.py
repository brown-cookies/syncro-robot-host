from ml.affect.model import build_mlp_pipeline, build_svc_pipeline


def test_svc_pipeline_has_exact_required_steps():
    """Verify that svc pipeline has exact required steps."""
    model = build_svc_pipeline()
    assert list(model.named_steps) == ["scaler", "classifier"]
    assert model.named_steps["classifier"].kernel == "rbf"
    assert model.named_steps["classifier"].class_weight == "balanced"


def test_mlp_pipeline_is_prespecified_and_shallow():
    """Verify that the MLP comparison uses the documented shallow architecture and scaler."""
    model = build_mlp_pipeline()
    classifier = model.named_steps["classifier"]
    assert list(model.named_steps) == ["scaler", "classifier"]
    assert classifier.hidden_layer_sizes == (64,)
    assert classifier.activation == "relu"
    assert classifier.solver == "adam"
    assert classifier.random_state == 42
    assert classifier.early_stopping is False
