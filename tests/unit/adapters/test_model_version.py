"""OBS-LOG FR-O6: adapters report a model_version; failure yields None, never raises."""

from __future__ import annotations

import json

import requests

from adapters.affect.classifier_detector import _artifact_version
from adapters.llm.ollama_meta import fetch_model_version

MODEL = "llama3.1:8b-instruct-q4_K_M"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _tags(*entries):
    return lambda *a, **k: _Resp({"models": list(entries)})


def test_ollama_digest_is_short_and_prefixed(monkeypatch):
    digest = "46e0c10c039e" + "0" * 52
    monkeypatch.setattr(
        "adapters.llm.ollama_meta.requests.get",
        _tags({"name": "other:1b", "digest": "ff" * 32}, {"name": MODEL, "digest": digest}),
    )
    assert fetch_model_version("http://x:11434/", MODEL) == "sha256:46e0c10c039e"


def test_ollama_matches_implicit_latest_tag(monkeypatch):
    monkeypatch.setattr(
        "adapters.llm.ollama_meta.requests.get",
        _tags({"name": "qwen:latest", "digest": "ab" * 32}),
    )
    assert fetch_model_version("http://x", "qwen") == "sha256:" + "ab" * 6


def test_ollama_unreachable_or_unknown_model_is_none(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("adapters.llm.ollama_meta.requests.get", boom)
    assert fetch_model_version("http://x", MODEL) is None
    monkeypatch.setattr("adapters.llm.ollama_meta.requests.get", _tags({"name": "a", "digest": "00"}))
    assert fetch_model_version("http://x", MODEL) is None


def test_affect_version_reads_sidecar_and_tolerates_absence(tmp_path):
    model = tmp_path / "affect_svc_v1.joblib"
    assert _artifact_version(model) is None  # no sidecar
    (tmp_path / "affect_svc_v1.joblib.json").write_text(
        json.dumps({"artifact_version": "affect_svc_v1"}), encoding="utf-8"
    )
    assert _artifact_version(model) == "affect_svc_v1"
