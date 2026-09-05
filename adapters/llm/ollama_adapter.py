"""Ollama implementation of the LLM adapter contract."""

from __future__ import annotations

import requests

from config.settings import Settings, get_settings


class LLMAdapterError(RuntimeError):
    """Raised when Ollama is unreachable or returns a failure."""


class OllamaLLMAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the OllamaLLMAdapter and establish its runtime state."""
        settings = settings or get_settings()
        self._base_url = settings.ollama_url.rstrip("/")
        self._model = settings.llm_model
        self._num_ctx = settings.ollama_num_ctx
        self._timeout_s = settings.ollama_timeout_s

    def generate(self, prompt: str) -> str:
        """Generate an LLM response from the supplied conversation state and context."""
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": self._num_ctx},
        }
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=self._timeout_s,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMAdapterError(
                f"Ollama request failed (base_url={self._base_url!r}, model={self._model!r}): {exc}"
            ) from exc

        try:
            data = response.json()
            text = data["response"].strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMAdapterError(
                f"Ollama returned an unexpected payload: {response.text[:500]!r}"
            ) from exc

        if not text:
            raise LLMAdapterError("Ollama returned an empty response.")
        return text
