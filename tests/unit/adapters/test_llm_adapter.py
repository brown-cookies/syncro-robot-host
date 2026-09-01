from __future__ import annotations

import pytest
import requests

from adapters.llm.ollama_adapter import LLMAdapterError, OllamaLLMAdapter


class FakeResponse:
    def __init__(self, payload=None, *, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_llm_builds_expected_request(monkeypatch, test_settings):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return FakeResponse({"response": " Hello world "})

    monkeypatch.setattr("adapters.llm.ollama_adapter.requests.post", fake_post)
    adapter = OllamaLLMAdapter(settings=test_settings)
    assert adapter.generate("hello") == "Hello world"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["kwargs"]["json"] == {
        "model": "test-model",
        "prompt": "hello",
        "stream": False,
        "options": {"num_ctx": 512},
    }
    assert captured["kwargs"]["timeout"] == 1.0


def test_llm_wraps_request_failure(monkeypatch, test_settings):
    monkeypatch.setattr(
        "adapters.llm.ollama_adapter.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("server unavailable")),
    )
    with pytest.raises(LLMAdapterError, match="Ollama request failed"):
        OllamaLLMAdapter(settings=test_settings).generate("hello")


def test_llm_rejects_malformed_json(monkeypatch, test_settings):
    monkeypatch.setattr(
        "adapters.llm.ollama_adapter.requests.post",
        lambda *a, **k: FakeResponse(ValueError("bad json"), text="not-json"),
    )
    with pytest.raises(LLMAdapterError, match="unexpected payload"):
        OllamaLLMAdapter(settings=test_settings).generate("hello")


def test_llm_rejects_missing_response(monkeypatch, test_settings):
    monkeypatch.setattr(
        "adapters.llm.ollama_adapter.requests.post",
        lambda *a, **k: FakeResponse({}, text="{}"),
    )
    with pytest.raises(LLMAdapterError, match="unexpected payload"):
        OllamaLLMAdapter(settings=test_settings).generate("hello")


def test_llm_rejects_empty_response(monkeypatch, test_settings):
    monkeypatch.setattr(
        "adapters.llm.ollama_adapter.requests.post",
        lambda *a, **k: FakeResponse({"response": "   "}),
    )
    with pytest.raises(LLMAdapterError, match="empty response"):
        OllamaLLMAdapter(settings=test_settings).generate("hello")
