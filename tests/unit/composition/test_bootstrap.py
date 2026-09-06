from __future__ import annotations

from pipeline import HostPipeline
from composition import bootstrap


def test_bootstrap_injects_one_settings_instance_everywhere(monkeypatch, test_settings):
    """Verify that bootstrap injects one settings instance everywhere."""
    seen = []

    class Fake:
        def __init__(self, settings):
            """Initialize the Fake and establish its runtime state."""
            seen.append(settings)

    monkeypatch.setattr(bootstrap, "MicrophoneAudioInput", Fake)
    monkeypatch.setattr(bootstrap, "WhisperSTTAdapter", Fake)
    monkeypatch.setattr(bootstrap, "OllamaLLMAdapter", Fake)
    monkeypatch.setattr(bootstrap, "PiperTTSAdapter", Fake)
    monkeypatch.setattr(bootstrap, "SpeakerAudioOutput", Fake)

    pipeline = bootstrap.build_wp102_pipeline(test_settings)
    assert isinstance(pipeline, HostPipeline)
    assert seen == [test_settings] * 5




def test_bootstrap_uses_classifier_affect_detector(monkeypatch, test_settings):
    """Verify that bootstrap constructs the WP-104 classifier detector."""
    class Fake:
        def __init__(self, settings):
            """Initialize a dependency double for the composition test."""
            pass

    class FakeStore:
        def __init__(self, path):
            """Initialize the storage double."""
            pass

    class FakeDetector:
        def __init__(self, path):
            """Initialize the classifier detector double."""
            self.path = path

    monkeypatch.setattr(bootstrap, "SQLiteStore", FakeStore)
    monkeypatch.setattr(bootstrap, "WhisperSTTAdapter", Fake)
    monkeypatch.setattr(bootstrap, "OllamaIntentClassifier", Fake)
    monkeypatch.setattr(bootstrap, "OllamaLLMAdapter", Fake)
    monkeypatch.setattr(bootstrap, "PiperTTSAdapter", Fake)
    monkeypatch.setattr(bootstrap, "MicrophoneAudioInput", Fake)
    monkeypatch.setattr(bootstrap, "SpeakerAudioOutput", Fake)

    import sys
    import types
    fake_graph_module = types.ModuleType("pipeline.graph")
    fake_graph_module.build_dialogue_graph = lambda **kwargs: kwargs["affect_detector"]
    monkeypatch.setitem(sys.modules, "pipeline.graph", fake_graph_module)

    import adapters.affect as affect
    monkeypatch.setattr(affect, "ClassifierAffectDetector", FakeDetector)

    result = bootstrap.build_wp103_components(test_settings)
    assert isinstance(result[0], FakeDetector)
    assert result[0].path == test_settings.affect_classifier_path
