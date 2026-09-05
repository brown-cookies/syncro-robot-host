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
