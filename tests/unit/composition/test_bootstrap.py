from __future__ import annotations

from pipeline import HostPipeline
from composition import bootstrap
from composition.bootstrap import HostComponents


def test_bootstrap_injects_one_settings_instance_everywhere(monkeypatch, test_settings):
    """Verify that bootstrap injects one settings instance everywhere."""
    seen = []

    class Fake:
        def __init__(self, settings):
            """Initialize the Fake and establish its runtime state."""
            seen.append(settings)

    monkeypatch.setattr(bootstrap, "MicrophoneAudioInput", Fake)
    monkeypatch.setattr(bootstrap, "WhisperSTTAdapter", Fake)
    monkeypatch.setattr(bootstrap, "OllamaIntentClassifier", Fake)
    monkeypatch.setattr(bootstrap, "OllamaLLMAdapter", Fake)
    monkeypatch.setattr(bootstrap, "PiperTTSAdapter", Fake)
    monkeypatch.setattr(bootstrap, "SpeakerAudioOutput", Fake)

    pipeline = bootstrap.build_host_pipeline(test_settings)
    assert isinstance(pipeline, HostPipeline)
    assert seen == [test_settings] * 5


def _patch_graph_dependencies(monkeypatch, test_settings):
    class Fake:
        def __init__(self, settings):
            """Initialize a dependency double for the composition test."""
            pass

    class FakeStore:
        def __init__(self, path):
            """Initialize the storage double."""
            pass

    monkeypatch.setattr(bootstrap, "SQLiteStore", FakeStore)
    monkeypatch.setattr(bootstrap, "WhisperSTTAdapter", Fake)
    monkeypatch.setattr(bootstrap, "OllamaIntentClassifier", Fake)
    monkeypatch.setattr(bootstrap, "OllamaLLMAdapter", Fake)
    monkeypatch.setattr(bootstrap, "PiperTTSAdapter", Fake)
    monkeypatch.setattr(bootstrap, "MicrophoneAudioInput", Fake)
    monkeypatch.setattr(bootstrap, "SpeakerAudioOutput", Fake)
    return FakeStore


def test_bootstrap_uses_development_affect_detector_by_default(monkeypatch, test_settings):
    """Verify that clean clones default to the deterministic affect fallback."""
    _patch_graph_dependencies(monkeypatch, test_settings)
    import sys
    import types
    fake_graph_module = types.ModuleType("pipeline.graph")
    setattr(fake_graph_module, "build_dialogue_graph", lambda **kwargs: kwargs["affect_detector"])
    monkeypatch.setitem(sys.modules, "pipeline.graph", fake_graph_module)

    result = bootstrap.build_host_components(test_settings)
    assert result.graph.__class__.__name__ == "DevelopmentAffectDetector"


def test_bootstrap_returns_host_components_not_a_positional_tuple(monkeypatch, test_settings):
    """S2 regression: build_host_components must return HostComponents by name,
    not a positional tuple (finding S2). New components (the runner, next) must be
    addable as a field without breaking any existing caller that reads by name.
    """
    _patch_graph_dependencies(monkeypatch, test_settings)
    import sys
    import types
    fake_graph_module = types.ModuleType("pipeline.graph")
    setattr(fake_graph_module, "build_dialogue_graph", lambda **kwargs: kwargs["affect_detector"])
    monkeypatch.setitem(sys.modules, "pipeline.graph", fake_graph_module)

    result = bootstrap.build_host_components(test_settings)

    assert isinstance(result, HostComponents)
    assert not isinstance(result, tuple)
    for field in ("graph", "store", "audio_input", "audio_output", "tts", "runner"):
        assert hasattr(result, field), f"HostComponents is missing field {field!r}"
    # Forward-declared for Phase 5 (F3, InteractionRunner); not populated yet.
    assert result.runner is None


def test_bootstrap_classifier_failure_falls_back_to_development(monkeypatch, test_settings):
    """Verify that a missing classifier artifact cannot abort graph construction."""
    _patch_graph_dependencies(monkeypatch, test_settings)
    import sys
    import types
    fake_graph_module = types.ModuleType("pipeline.graph")
    setattr(fake_graph_module, "build_dialogue_graph", lambda **kwargs: kwargs["affect_detector"])
    monkeypatch.setitem(sys.modules, "pipeline.graph", fake_graph_module)

    test_settings = test_settings.__class__(
        affect_detector_backend="classifier",
        affect_classifier_path="/missing/affect.joblib",
    )
    result = bootstrap.build_host_components(test_settings)
    assert result.graph.__class__.__name__ == "DevelopmentAffectDetector"
