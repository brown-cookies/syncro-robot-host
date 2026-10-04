from __future__ import annotations

import pytest

from config.settings import Settings
from observability import Severity, build_emitter
from observability.sinks import ConsoleSink, FileSink


def test_settings_reads_logging_env(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_OUTPUT", "FILE")
    monkeypatch.setenv("LOG_FILE_PATH", "./logs/x.jsonl")
    monkeypatch.setenv("LOG_INCLUDE_TEXT", "true")
    s = Settings.from_env()
    assert (s.log_level, s.log_output, s.log_file_path, s.log_include_text) == (
        "DEBUG", "file", "./logs/x.jsonl", True,
    )


def test_settings_rejects_unknown_log_output(monkeypatch) -> None:
    monkeypatch.setenv("LOG_OUTPUT", "syslog")
    with pytest.raises(ValueError, match="LOG_OUTPUT"):
        Settings.from_env()


def test_default_is_console_info_without_text() -> None:
    emitter = build_emitter(Settings())
    assert emitter.level is Severity.INFO
    assert isinstance(emitter._sinks[0], ConsoleSink)
    assert emitter._include_text is False


def test_include_text_is_ignored_unless_level_is_debug() -> None:
    assert build_emitter(Settings(log_level="INFO", log_include_text=True))._include_text is False
    assert build_emitter(Settings(log_level="debug", log_include_text=True))._include_text is True


def test_file_output_uses_file_sink(tmp_path) -> None:
    emitter = build_emitter(Settings(log_output="file", log_file_path=str(tmp_path / "e.jsonl")))
    assert isinstance(emitter._sinks[0], FileSink)
    emitter.close()


def test_unusable_file_path_falls_back_to_console(tmp_path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    emitter = build_emitter(Settings(log_output="file", log_file_path=str(blocker / "e.jsonl")))
    assert isinstance(emitter._sinks[0], ConsoleSink)


def test_missing_file_path_falls_back_to_console() -> None:
    emitter = build_emitter(Settings(log_output="file", log_file_path=""))
    assert isinstance(emitter._sinks[0], ConsoleSink)


def test_unknown_level_falls_back_to_info() -> None:
    assert build_emitter(Settings(log_level="LOUD")).level is Severity.INFO
