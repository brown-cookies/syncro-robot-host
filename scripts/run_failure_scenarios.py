"""Run failure / degradation scenarios and check the traces they leave (OBS-LOG item 4).

Each scenario drives ONE interaction through the real dialogue graph and the real
InteractionRunner, writing to a real JSONL file and a real SQLite file in a temp
directory. It then prints the timeline (same renderer as scripts.show_trace) and
checks it against what the spec says a failure trace must look like.

    python -m scripts.run_failure_scenarios                  # all, offline, deterministic
    python -m scripts.run_failure_scenarios tts_timeout      # one scenario
    python -m scripts.run_failure_scenarios --list

    # Real Whisper / Ollama / Piper / affect model, with a 16 kHz mono WAV of speech:
    python -m scripts.run_failure_scenarios --real --wav my_utterance.wav

Offline mode injects the fault into a fake component, so it proves the observability
layer; it says nothing about how real Whisper, Ollama or Piper fail. ``--real`` does:
real components, with the fault produced by configuration (Ollama pointed at a dead
port, a 1 ms TTS timeout, silence for STT) or by an injected affect detector.

Exit status is 1 if any check fails.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
import sys
import tempfile
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from uuid import UUID

import numpy as np

from adapters.contracts import STT  # noqa: F401  (documents the shapes the fakes mimic)
from adapters.llm.intent_classifier import IntentClassifierError
from adapters.llm.ollama_adapter import LLMAdapterError
from audio.resample import to_pcm16_16k
from observability.factory import build_emitter
from pipeline.contracts import DegradationReason
from pipeline.graph import build_dialogue_graph
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext
from scripts import show_trace
from storage.sqlite_store import SQLiteStore

USER_ID, SESSION_ID = "scenario-user", "scenario-session"
SENTINEL = "zebra-secret-words about my dentist"  # must never appear in an INFO log
SAMPLE_RATE = 16_000

REQUIRED_ERROR_KEYS = {
    "error_type", "error_code", "component", "operation",
    "message", "recoverable", "retry_count", "traceback",
}
_DEGRADATION_REASONS = set(DegradationReason.__args__) if hasattr(
    DegradationReason, "__args__") else set()


# --------------------------------------------------------------------- fakes

class FakeSTT:
    model_name, model_version = "tiny.en", "stt-v1"

    def __init__(self, transcript: str = SENTINEL) -> None:
        self._transcript = transcript

    def transcribe(self, audio, sample_rate):
        return self._transcript


class FakeIntent:
    model_name, model_version = "qwen-test", "sha256:intent"

    def __init__(self, confidence: float = 0.91, error: Exception | None = None) -> None:
        self._confidence, self._error = confidence, error

    def classify(self, transcript):
        if self._error:
            raise self._error
        return "ask_status", self._confidence, {}


class FakeAffect:
    model_name, model_version = "affect-svc", "v-test"

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def detect(self, audio, sample_rate):
        if self._error:
            raise self._error
        return "Low"


class FakeLLM:
    model_name, model_version = "qwen-test", "sha256:llm"

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def generate(self, prompt):
        if self._error:
            raise self._error
        return json.dumps({"response_text": "All good.", "proposed_action": "respond"})


class FakeTTS:
    def synthesize(self, text):
        return np.zeros(1_600, dtype=np.float32), SAMPLE_RATE


class HangingTTS:
    """Blocks until released: a deterministic stand-in for a stuck engine."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def synthesize(self, text):
        self.release.wait(timeout=10)
        return np.zeros(1_600, dtype=np.float32), SAMPLE_RATE


class BrokenAffect:
    """Injected into the real stack (--real): everything else stays real."""

    model_name, model_version = "affect-svc", "broken"

    def detect(self, audio, sample_rate):
        raise RuntimeError("injected affect failure")


# ----------------------------------------------------------------- scenarios

Match = tuple  # (component, event_type) or (component, event_type, severity)


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    outcome: str  # "completed" | "failed"
    must_have: tuple[Match, ...] = ()
    must_not_have: tuple[Match, ...] = ()
    db_degradation_reason: str | None = None
    # interaction_failed metadata the runner should record, e.g. {"stage": "llm"}
    failed_with: dict[str, str] = field(default_factory=dict)
    expect_text_only: bool = False  # tts_timeout: response delivered without audio
    # What `show_trace --list` should call it: ok | degraded | FAILED
    list_outcome: str = "ok"
    fake: dict[str, Any] = field(default_factory=dict)
    real_supported: bool = True


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "baseline", "control: a clean interaction leaves a clean trace", "completed",
        must_not_have=(("*", "stage_failed"), ("*", "model_inference_failed"),
                       ("*", "degradation_applied"), ("*", "interaction_failed")),
    ),
    Scenario(
        "empty_transcript", "STT returns nothing (silence / unintelligible)", "failed",
        must_have=(("stt", "model_inference_completed"), ("stt", "stage_failed", "ERROR"),
                   ("runner", "interaction_failed", "ERROR"),
                   ("runner", "degradation_applied", "WARNING")),
        must_not_have=(("intent", "stage_started"), ("runner", "interaction_completed")),
        db_degradation_reason="pipeline_failure", list_outcome="FAILED",
        failed_with={"wire_code": "pipeline_failure"},
        fake={"stt": lambda: FakeSTT("   ")},
    ),
    Scenario(
        "ollama_down_intent", "Ollama unreachable at the intent stage", "failed",
        must_have=(("intent", "model_inference_failed", "ERROR"),
                   ("intent", "stage_failed", "ERROR"),
                   ("runner", "interaction_failed", "ERROR")),
        must_not_have=(("llm", "stage_started"), ("runner", "interaction_completed")),
        db_degradation_reason="pipeline_failure", list_outcome="FAILED",
        failed_with={"stage": "intent"},
        fake={"intent": lambda: FakeIntent(error=IntentClassifierError("Ollama request failed"))},
    ),
    Scenario(
        "ollama_down_llm", "Ollama unreachable at the reasoning (LLM) stage", "failed",
        must_have=(("intent", "model_inference_completed"),
                   ("llm", "model_inference_failed", "ERROR"),
                   ("llm", "stage_failed", "ERROR"),
                   ("runner", "interaction_failed", "ERROR")),
        must_not_have=(("policy", "stage_started"),),
        db_degradation_reason="pipeline_failure", list_outcome="FAILED",
        failed_with={"stage": "llm"},
        fake={"llm": lambda: FakeLLM(error=LLMAdapterError("Ollama request failed"))},
        real_supported=False,  # a dead Ollama fails at intent first
    ),
    Scenario(
        "tts_timeout", "TTS engine hangs: text-only fallback, interaction still completes",
        "completed",
        must_have=(("runner", "degradation_applied", "WARNING"),
                   ("runner", "interaction_completed")),
        must_not_have=(("runner", "interaction_failed"),),
        db_degradation_reason="tts_timeout", list_outcome="degraded",
        expect_text_only=True,
        fake={"tts": lambda: HangingTTS(), "tts_timeout_s": 0.3},
    ),
    Scenario(
        "affect_fallback", "affect detector fails: falls back to a safe level, carries on",
        "completed",
        must_have=(("affect", "model_inference_failed", "ERROR"),
                   ("affect", "degradation_applied", "WARNING"),
                   ("affect", "stage_completed"), ("runner", "interaction_completed")),
        must_not_have=(("runner", "interaction_failed"),),
        db_degradation_reason="affect_detector_failure", list_outcome="degraded",
        fake={"affect": lambda: FakeAffect(error=RuntimeError("affect model exploded"))},
    ),
    Scenario(
        "clarify_low_confidence", "low-confidence intent: context and LLM stages are skipped",
        "completed",
        must_have=(("context", "stage_skipped"), ("llm", "stage_skipped"),
                   ("runner", "interaction_completed")),
        must_not_have=(("llm", "model_inference_started"), ("runner", "interaction_failed")),
        fake={"intent": lambda: FakeIntent(confidence=0.30)},
        real_supported=False,  # cannot force a low-confidence answer from a real model
    ),
)


# ----------------------------------------------------------------------- rigs

@dataclass
class Rig:
    runner: InteractionRunner
    emitter: Any
    log_path: Path
    db_path: Path
    audio: np.ndarray
    cleanup: Callable[[], None] = lambda: None


def _log_settings(tmp: Path) -> SimpleNamespace:
    return SimpleNamespace(log_level="INFO", log_include_text=False, log_output="file",
                           log_file_path=str(tmp / "events.jsonl"))


def build_fake_rig(sc: Scenario, tmp: Path) -> Rig:
    emitter = build_emitter(_log_settings(tmp))
    store = SQLiteStore(str(tmp / "syncro.db"))
    store.ensure_user(USER_ID)
    make = lambda key, default: sc.fake.get(key, default)()  # noqa: E731
    tts = make("tts", FakeTTS)
    graph = build_dialogue_graph(
        stt=make("stt", FakeSTT), intent_classifier=make("intent", FakeIntent),
        llm=make("llm", FakeLLM), store=store, affect_detector=make("affect", FakeAffect),
        confidence_threshold=0.60, context_top_k=5, deadline_proximity_hours=2,
        grace_window_minutes=15, default_lead_time=15, emitter=emitter,
    )
    runner = InteractionRunner(
        graph=graph, store=store, tts=tts, resampler=to_pcm16_16k, emitter=emitter,
        tts_timeout_s=float(sc.fake.get("tts_timeout_s", 2.0)),
    )

    def cleanup() -> None:
        if hasattr(tts, "release"):
            tts.release.set()

    return Rig(runner, emitter, tmp / "events.jsonl", tmp / "syncro.db",
               np.zeros(1_600, dtype=np.float32), cleanup)


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as wav:
        if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) != (1, SAMPLE_RATE, 2):
            raise SystemExit(f"{path}: need 16 kHz, mono, 16-bit PCM")
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def build_real_rig(sc: Scenario, tmp: Path, wav_audio: np.ndarray | None) -> Rig:
    """Real adapters via the composition root; the fault comes from configuration."""
    from composition.bootstrap import build_host_components
    from config.settings import get_settings

    changes: dict[str, Any] = {
        "log_output": "file", "log_level": "INFO", "log_include_text": False,
        "log_file_path": str(tmp / "events.jsonl"), "db_path": str(tmp / "syncro.db"),
    }
    affect = None
    audio = wav_audio
    if sc.name == "empty_transcript":
        audio = np.zeros(SAMPLE_RATE * 3, dtype=np.float32)  # silence
    elif sc.name == "ollama_down_intent":
        changes["ollama_url"] = "http://127.0.0.1:9"  # discard port: refused at once
    elif sc.name == "tts_timeout":
        changes["tts_timeout_s"] = 0.001
    elif sc.name == "affect_fallback":
        affect = BrokenAffect()
    if audio is None:
        raise SystemExit(f"scenario {sc.name!r} needs speech: pass --wav FILE")
    settings = dataclasses.replace(get_settings(), **changes)
    components = build_host_components(settings, affect_detector=affect)
    store = components.store
    store.ensure_user(USER_ID)
    return Rig(components.runner, components.emitter, tmp / "events.jsonl",
               tmp / "syncro.db", audio, components.runner.close)


# --------------------------------------------------------------------- checks

Check = tuple[bool, str]


def read_events(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text("utf-8").splitlines() if line.strip()]


def read_rows(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            "SELECT trace_id, degradation_reason, latency_ms FROM decision_trace")]
    finally:
        conn.close()


def _matches(event: dict, match: Match) -> bool:
    component, event_type, *severity = match
    return ((component == "*" or event["component"] == component)
            and event["event_type"] == event_type
            and (not severity or event["severity"] == severity[0]))


def invariant_checks(events: list[dict], rows: list[dict]) -> list[Check]:
    """Properties every trace must have, whatever the scenario."""
    out: list[Check] = []
    ids = {e["trace_id"] for e in events}
    out.append((len(ids) == 1, f"one trace_id across all {len(events)} events ({len(ids)} found)"))
    row_ids = [r["trace_id"] for r in rows]
    out.append((len(rows) == 1 and ids == set(row_ids),
                f"JSONL trace_id matches the single decision_trace row ({row_ids})"))

    terminal = [e for e in events
                if e["event_type"] in ("interaction_completed", "interaction_failed")]
    out.append((len(terminal) == 1, f"exactly one interaction terminal event ({len(terminal)})"))
    if terminal and events:
        out.append((events[-1] is terminal[0] or events[-1]["event_id"] == terminal[0]["event_id"],
                    "nothing is logged after the interaction terminal event"))

    # every started stage / model call has exactly one terminal child
    for started_type, terminals in (
        ("stage_started", ("stage_completed", "stage_failed", "stage_skipped")),
        ("model_inference_started", ("model_inference_completed", "model_inference_failed")),
    ):
        for s in (e for e in events if e["event_type"] == started_type):
            kids = [e for e in events
                    if e["parent_event_id"] == s["event_id"] and e["event_type"] in terminals]
            out.append((len(kids) == 1,
                        f"{s['component']} {started_type} has exactly one terminal event ({len(kids)})"))

    for e in events:
        if e["status"] == "failure" or e["event_type"].endswith("_failed"):
            err = e.get("error") or {}
            missing = REQUIRED_ERROR_KEYS - set(err)
            out.append((not missing, f"{e['component']} {e['event_type']} error shape"
                        + (f" (missing {sorted(missing)})" if missing else "")))
        if e["event_type"] in ("stage_failed", "model_inference_failed"):
            out.append((e["duration_ms"] is not None,
                        f"{e['component']} {e['event_type']} carries a duration"))
        if e["event_type"] == "degradation_applied":
            reason = e["metadata"].get("reason_code")
            ok = e["severity"] == "WARNING" and (not _DEGRADATION_REASONS
                                                  or reason in _DEGRADATION_REASONS)
            out.append((ok, f"degradation_applied reason_code {reason!r} is WARNING and in the contract"))
    completed = next((e for e in events if e["event_type"] == "interaction_completed"), None)
    if completed is not None and len(rows) == 1:
        logged, stored = completed["metadata"].get("degradation_reason"), rows[0]["degradation_reason"]
        out.append((logged == stored,
                    f"interaction_completed.degradation_reason ({logged!r}) matches the stored row ({stored!r})"))
    blob = json.dumps(events)
    out.append((SENTINEL not in blob and "dentist" not in blob,
                "no raw transcript text anywhere in the INFO log"))
    return out


def scenario_checks(sc: Scenario, events: list[dict], rows: list[dict],
                    error: InteractionError | None, result: Any,
                    list_outcome: str | None = None) -> list[Check]:
    out: list[Check] = []
    if list_outcome is not None:
        out.append((list_outcome == sc.list_outcome,
                    f"show_trace --list calls it {sc.list_outcome!r} (got {list_outcome!r})"))
    out.append(((error is not None) == (sc.outcome == "failed"),
                f"interaction {'failed' if error else 'completed'} as expected ({sc.outcome})"))
    for match in sc.must_have:
        out.append((any(_matches(e, match) for e in events), f"has {' / '.join(match)}"))
    for match in sc.must_not_have:
        out.append((not any(_matches(e, match) for e in events), f"has no {' / '.join(match)}"))
    if sc.failed_with:
        failed = next((e for e in events if e["event_type"] == "interaction_failed"), None)
        for key, want in sc.failed_with.items():
            got = (failed or {}).get("metadata", {}).get(key)
            out.append((got == want, f"interaction_failed {key} == {want!r} (got {got!r})"))
    if sc.db_degradation_reason is not None:
        got = rows[0]["degradation_reason"] if rows else None
        out.append((got == sc.db_degradation_reason,
                    f"decision_trace.degradation_reason == {sc.db_degradation_reason!r} (got {got!r})"))
    if sc.outcome == "completed" and sc.db_degradation_reason is None and rows:
        out.append((rows[0]["degradation_reason"] is None,
                    f"decision_trace.degradation_reason is null (got {rows[0]['degradation_reason']!r})"))
    if sc.expect_text_only and result is not None:
        out.append((result.tts_audio.size == 0 and bool(result.response_payload.get("tts_text")),
                    "response text delivered with no audio (fallback channel)"))
    return out


# ------------------------------------------------------------------- driver

def run_scenario(sc: Scenario, *, real: bool, wav_audio: np.ndarray | None,
                 out=sys.stdout) -> bool:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        rig = build_real_rig(sc, tmp, wav_audio) if real else build_fake_rig(sc, tmp)
        error: InteractionError | None = None
        result = None
        try:
            session = SessionContext(SESSION_ID, USER_ID, started_monotonic=_now())
            try:
                result = rig.runner.run(session=session, audio=rig.audio, sample_rate=SAMPLE_RATE)
            except InteractionError as exc:
                error = exc
        finally:
            rig.cleanup()
            rig.emitter.close()
        events, rows = read_events(rig.log_path), read_rows(rig.db_path)
        listed = show_trace.list_traces(rig.log_path) if events else []
        list_outcome = listed[0]["outcome"] if listed else None

    print(f"\n{'=' * 100}\n{sc.name}: {sc.description}  [{'real' if real else 'offline'}]\n{'=' * 100}",
          file=out)
    if events:
        print(f"# {events[0]['trace_id']}", file=out)
        print(show_trace.render(events), file=out)
    else:
        print("(no events were logged)", file=out)
    if error is not None:
        print(f"\nraised InteractionError: stage={error.stage!r} wire_code={error.wire_code!r} "
              f"degradation_reason={error.degradation_reason!r}", file=out)
    if result is not None:
        print(f"\nresult: degradation_reason={result.degradation_reason!r} "
              f"audio_samples={result.tts_audio.size}", file=out)

    checks = scenario_checks(sc, events, rows, error, result, list_outcome) + invariant_checks(events, rows)
    print("\nchecks:", file=out)
    for ok, message in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {message}", file=out)
    return all(ok for ok, _ in checks)


def _now() -> float:
    from time import monotonic
    return monotonic()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="scenario names (default: all)")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument("--real", action="store_true", help="use the real components")
    parser.add_argument("--wav", help="16 kHz mono 16-bit WAV of speech, for --real")
    args = parser.parse_args(argv)

    if args.list:
        for sc in SCENARIOS:
            print(f"{sc.name:<24} {sc.description}"
                  + ("" if sc.real_supported else "   (offline only)"))
        return 0
    by_name = {sc.name: sc for sc in SCENARIOS}
    unknown = [n for n in args.names if n not in by_name]
    if unknown:
        parser.error(f"unknown scenario(s): {', '.join(unknown)}")
    chosen = [by_name[n] for n in args.names] or list(SCENARIOS)
    if args.real:
        skipped = [sc.name for sc in chosen if not sc.real_supported]
        chosen = [sc for sc in chosen if sc.real_supported]
        if skipped:
            print(f"skipping (offline only): {', '.join(skipped)}", file=sys.stderr)
    wav_audio = load_wav(args.wav) if args.wav else None

    results = {sc.name: run_scenario(sc, real=args.real, wav_audio=wav_audio) for sc in chosen}
    print(f"\n{'=' * 100}\nsummary")
    for name, ok in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
