"""Resolve the identity of a locally served Ollama model for OBS-LOG FR-O6."""

from __future__ import annotations

import requests

_DIGEST_CHARS = 12


def fetch_model_version(base_url: str, model: str, *, timeout_s: float = 2.0) -> str | None:
    """Return ``sha256:<12 hex>`` for ``model`` as reported by Ollama, else None.

    The tag (``llama3.1:8b-instruct-q4_K_M``) names the model but can be
    re-pulled to different weights; the digest identifies the exact build.
    Observability must not affect behavior, so any failure (server down,
    model not pulled, unexpected payload) yields None instead of raising.
    """
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout_s)
        response.raise_for_status()
        wanted = {model, f"{model}:latest"}
        for entry in response.json().get("models", []):
            if entry.get("name") in wanted or entry.get("model") in wanted:
                digest = str(entry.get("digest") or "")
                digest = digest.removeprefix("sha256:")
                return f"sha256:{digest[:_DIGEST_CHARS]}" if digest else None
    except Exception:  # noqa: BLE001 - observability must never fail the model call
        return None
    return None
