"""Central redaction (OBS-LOG spec, Section 7). Runs before any sink sees a record.

Policy:
- credentials / tokens / secrets / auth values: always redacted
- raw audio and byte/array payloads: always omitted
- transcript / final_response (and similar): hash-only by default; full text
  only when ``include_text`` is true (the emitter grants that only for DEBUG
  events with LOG_INCLUDE_TEXT=true)
- prompts: never logged, regardless of the flag (length + hash only)
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_KEY = re.compile(
    r"(passw(or)?d|secret|api[_-]?key|authorization|credential|(^|[_-])token$)"
)
_AUDIO_KEYS = frozenset({"audio", "raw_audio", "samples", "waveform", "pcm"})
_TEXT_KEYS = frozenset(
    {"transcript", "final_response", "draft_response",
        "response_text", "input_text", "text"}
)
_NEVER_TEXT_KEYS = frozenset({"prompt", "system_prompt", "messages"})

_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_KV_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret)(\s*[=:]\s*)\S+")

_MAX_DEPTH = 6
_MAX_ITEMS = 200
_MAX_STR = 4000


def hash_text(text: str) -> str:
    """SHA-256 of the UTF-8 text, truncated to 16 hex chars (spec Section 7)."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _scrub(text: str) -> str:
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _KV_SECRET.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return text if len(text) <= _MAX_STR else text[:_MAX_STR] + "...[truncated]"


def redact(record: dict[str, Any], *, include_text: bool) -> dict[str, Any]:
    """Return a redacted deep copy of ``record``. Never mutates the input."""
    return _walk(record, include_text, 0)


def _walk(value: Any, include_text: bool, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return "[TRUNCATED]"

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            lowered = name.lower()
            if _SECRET_KEY.search(lowered):
                out[name] = REDACTED
            elif lowered in _AUDIO_KEYS:
                out[name] = "[AUDIO OMITTED]"
            elif lowered in _TEXT_KEYS or lowered in _NEVER_TEXT_KEYS:
                if include_text and lowered in _TEXT_KEYS and isinstance(item, str):
                    out[name] = _scrub(item)
                elif isinstance(item, str):
                    out[f"{name}_length"] = len(item)
                    out[f"{name}_hash"] = hash_text(item)
                else:
                    out[name] = REDACTED
            else:
                out[name] = _walk(item, include_text, depth + 1)
        return out

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_walk(v, include_text, depth + 1) for v in list(value)[:_MAX_ITEMS]]
    if isinstance(value, str):
        return _scrub(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[{len(value)} BYTES OMITTED]"
    if hasattr(value, "shape") and hasattr(value, "dtype"):  # numpy-like
        return f"[ARRAY {tuple(value.shape)} OMITTED]"
    return _scrub(str(value))[:500]
