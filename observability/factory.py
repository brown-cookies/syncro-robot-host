"""Build an Emitter from Settings (LOG_LEVEL / LOG_OUTPUT / LOG_FILE_PATH / LOG_INCLUDE_TEXT)."""

from __future__ import annotations

import logging
from typing import Any

from observability.emitter import Emitter
from observability.events import Severity
from observability.sinks import ConsoleSink, FileSink, Sink

logger = logging.getLogger(__name__)


def _parse_level(raw: str) -> Severity:
    try:
        return Severity[str(raw).strip().upper()]
    except KeyError:
        logger.warning("Unknown LOG_LEVEL %r; falling back to INFO", raw)
        return Severity.INFO


def build_emitter(settings: Any) -> Emitter:
    """Never fails host startup (spec Section 8/9): a bad file path falls back to console."""
    level = _parse_level(settings.log_level)
    # Full text needs BOTH LOG_INCLUDE_TEXT=true and LOG_LEVEL=DEBUG.
    include_text = bool(settings.log_include_text) and level is Severity.DEBUG

    sink: Sink
    if settings.log_output == "file":
        try:
            sink = FileSink(settings.log_file_path)
        except (OSError, ValueError) as exc:
            logger.warning(
                "LOG_OUTPUT=file but %r is unusable (%s); falling back to console",
                settings.log_file_path,
                exc,
            )
            sink = ConsoleSink()
    else:
        sink = ConsoleSink()

    return Emitter([sink], level=level, include_text=include_text)
