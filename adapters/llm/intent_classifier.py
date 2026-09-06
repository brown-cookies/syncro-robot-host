"""Ollama-backed intent classifier for WP-103 Node 1."""

from __future__ import annotations

import json
import re

import requests

from config.settings import Settings, get_settings
from pipeline.contracts import ALLOWED_INTENTS




class IntentClassifierError(RuntimeError):
    """Raised when intent classification cannot produce a valid result."""


class OllamaIntentClassifier:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._base_url = settings.ollama_url.rstrip("/")
        self._model = settings.llm_model
        self._num_ctx = settings.ollama_num_ctx
        self._timeout_s = settings.ollama_timeout_s
        self._threshold = settings.intent_confidence_threshold

    def classify(self, transcript: str) -> tuple[str, float, dict[str, object]]:
        prompt = f"""You are a strict SYNCRO intent classifier.
Classify the user's utterance into exactly one of these intents:
{', '.join(sorted(ALLOWED_INTENTS))}

Return ONLY valid JSON with this shape:
{{"intent":"...","confidence":0.0,"slots":{{}}}}

Rules:
- confidence is a number from 0 to 1.
- For snooze_reminder, slots MUST contain integer snooze_minutes.
- Do not invent an intent outside the allowed set.
- Do not add explanatory text.

User utterance:
{transcript}
"""
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"num_ctx": self._num_ctx},
        }
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            data = response.json()
            raw = data["response"]
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise IntentClassifierError(f"Intent classification request failed: {exc}") from exc

        parsed = self._parse_json(raw)
        intent = parsed.get("intent")
        confidence = parsed.get("confidence")
        slots = parsed.get("slots", {})
        if intent not in ALLOWED_INTENTS:
            raise IntentClassifierError(f"Invalid intent returned by model: {intent!r}")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise IntentClassifierError(f"Invalid confidence returned by model: {confidence!r}")
        if not isinstance(slots, dict):
            raise IntentClassifierError("Intent classifier returned non-object slots.")
        if intent == "snooze_reminder":
            value = slots.get("snooze_minutes")
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise IntentClassifierError("snooze_reminder requires positive integer snooze_minutes.")

        return str(intent), float(confidence), dict(slots)

    @staticmethod
    def _parse_json(raw: object) -> dict[str, object]:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            raise IntentClassifierError("Ollama intent response was not JSON text.")
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                raise IntentClassifierError("Ollama intent response was not valid JSON.") from exc
            try:
                value = json.loads(match.group(0))
            except json.JSONDecodeError as nested:
                raise IntentClassifierError("Ollama intent response was not valid JSON.") from nested
        if not isinstance(value, dict):
            raise IntentClassifierError("Ollama intent response must be a JSON object.")
        return value
