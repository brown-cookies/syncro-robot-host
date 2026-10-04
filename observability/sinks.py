"""Console and file sinks. Both write the same JSON-lines schema (spec Section 8)."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Protocol


def to_json_line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)


class Sink(Protocol):
    def write(self, record: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


class ConsoleSink:
    """One JSON line per event on stderr (resolved per write, so it follows
    redirection and keeps stdout free for the existing script output)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        line = to_json_line(record)
        with self._lock:
            print(line, file=sys.stderr, flush=True)

    def close(self) -> None:
        return None


class FileSink:
    """Append-only JSONL file. Opens eagerly so a bad path fails at startup
    (where the factory can fall back to console), not mid-interaction."""

    def __init__(self, path: str) -> None:
        if not path:
            raise ValueError("LOG_FILE_PATH is empty")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._path = target
        self._lock = threading.Lock()
        self._handle = open(target, "a", encoding="utf-8", newline="\n")

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: dict[str, Any]) -> None:
        line = to_json_line(record)
        with self._lock:
            self._handle.write(line + "\n")
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            self._handle.close()
