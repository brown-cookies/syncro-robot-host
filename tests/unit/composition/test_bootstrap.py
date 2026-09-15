from __future__ import annotations

from pipeline import HostPipeline
from composition import bootstrap
from composition.bootstrap import HostComponents
from pipeline.interaction import InteractionRunner


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
    # The warm-up call hits the network directly (it's a raw requests.post,
    # not an adapter class) -- patch it out here too so every test using
    # this fixture stays offline, same as the adapter doubles above.
    monkeypatch.setattr(bootstrap, "_warm_up_llm", lambda settings: None)
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
    assert isinstance(result.runner, InteractionRunner)
    assert result.runner._graph is result.graph
    assert result.runner._store is result.store
    assert result.runner._tts is result.tts


def test_bootstrap_calls_warm_up_before_building_components(monkeypatch, test_settings):
    """build_host_components must warm the shared LLM model before doing
    anything else, so a cold Ollama load lands in startup, not in the first
    interaction's intent_timeout_s/reasoning_timeout_s budget (D5)."""
    _patch_graph_dependencies(monkeypatch, test_settings)
    import sys
    import types
    fake_graph_module = types.ModuleType("pipeline.graph")
    setattr(fake_graph_module, "build_dialogue_graph", lambda **kwargs: kwargs["affect_detector"])
    monkeypatch.setitem(sys.modules, "pipeline.graph", fake_graph_module)

    calls = []
    monkeypatch.setattr(bootstrap, "_warm_up_llm", lambda settings: calls.append(settings))

    bootstrap.build_host_components(test_settings)

    assert calls == [test_settings]


def test_warm_up_llm_sends_load_only_request_with_configured_model(monkeypatch, test_settings):
    """_warm_up_llm should send Ollama's documented load-only call (empty
    prompt) for settings.llm_model, using llm_warmup_timeout_s -- not the
    per-turn intent_timeout_s/reasoning_timeout_s budget."""
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            """No-op: the warm-up call doesn't need a successful body."""

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse()

    monkeypatch.setattr(bootstrap.requests, "post", fake_post)

    bootstrap._warm_up_llm(test_settings)

    assert len(calls) == 1
    url, payload, timeout = calls[0]
    assert url == f"{test_settings.ollama_url}/api/generate"
    assert payload["model"] == test_settings.llm_model
    assert payload["prompt"] == ""
    assert payload["keep_alive"] == test_settings.ollama_keep_alive
    assert timeout == test_settings.llm_warmup_timeout_s


def test_warm_up_llm_failure_is_swallowed_not_raised(monkeypatch, test_settings, caplog):
    """A cold/unreachable Ollama at warm-up time must not abort composition
    -- the identical failure will surface as a real, correctly classified
    IntentClassifierError/LLMAdapterError on the first interaction (F4)."""
    import requests

    def fake_post(url, json, timeout):
        raise requests.exceptions.ReadTimeout("simulated cold-load timeout")

    monkeypatch.setattr(bootstrap.requests, "post", fake_post)

    bootstrap._warm_up_llm(test_settings)  # must not raise


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
