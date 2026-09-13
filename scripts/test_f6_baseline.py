"""Measure the current unmodified F6 two-LLM WP-103 path.

This script is intentionally an observation-only benchmark. It does not change
runtime settings, model parameters, timeouts, keep_alive behavior, or STT
configuration. It follows the live-run setup in ``scripts/run_wp103.py`` and
uses the already-wired ``HostComponents.runner`` from the Phase 8 code.

Default experiment:
    3 warm-up interactions + 10 measured interactions

Evidence written under ``evidences/``:
    f6_baseline_<timestamp>.txt

The current TTS adapter is blocking and exposes synthesis completion rather
than TTS onset. Therefore ``interaction_to_tts_completion_s`` is reported as
the observable latency proxy; the limitation is recorded in the evidence.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from composition.bootstrap import build_host_components
from config.settings import Settings, get_settings
from pipeline.interaction import SessionContext

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidences"
DEFAULT_USER_ID = "f6-baseline-user"


@dataclass(slots=True)
class StageProbe:
    name: str
    elapsed_s: float = 0.0
    calls: int = 0

    def wrap(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            self.calls += 1
            try:
                return fn(*args, **kwargs)
            finally:
                self.elapsed_s += time.monotonic() - started

        return wrapped

    def reset(self) -> None:
        self.elapsed_s = 0.0
        self.calls = 0


@dataclass(slots=True)
class RunRecord:
    run_index: int
    warmup: bool
    trace_id: str
    intent: str | None
    intent_confidence: float | None
    affect_level: str | None
    transcript: str | None
    stt_s: float
    intent_s: float
    context_s: float
    reasoning_s: float
    policy_s: float
    affect_s: float
    tts_s: float
    graph_s: float
    interaction_to_tts_completion_s: float
    llm_total_s: float
    total_observed_s: float
    stage_timing_source: str


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _install_ollama_probe(probes: dict[str, StageProbe]) -> Callable[[], None]:
    """Patch requests.post to time the two real Ollama /api/generate calls."""
    import requests

    original = requests.post

    def wrapped(url: Any, *args: Any, **kwargs: Any) -> Any:
        payload = kwargs.get("json")
        stage = None
        if isinstance(url, str) and url.rstrip("/").endswith("/api/generate"):
            prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
            stage = "intent" if "strict SYNCRO intent classifier" in str(prompt) else "reasoning"
        if stage is None:
            return original(url, *args, **kwargs)
        return probes[stage].wrap(original)(url, *args, **kwargs)

    requests.post = wrapped
    return lambda: setattr(requests, "post", original)


def _install_method_probe(obj: Any, method_name: str, probe: StageProbe) -> Callable[[], None]:
    original = getattr(obj, method_name)
    setattr(obj, method_name, probe.wrap(original))
    return lambda: setattr(obj, method_name, original)


def _install_policy_probe(probe: StageProbe) -> Callable[[], None]:
    import pipeline.nodes.policy as policy_module

    original = policy_module.apply_policy
    policy_module.apply_policy = probe.wrap(original)
    return lambda: setattr(policy_module, "apply_policy", original)


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "mean_s": None, "median_s": None, "p95_s": None, "min_s": None, "max_s": None}
    ordered = sorted(values)
    n = len(ordered)
    mean = sum(ordered) / n
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    rank = max(0, min(n - 1, int((n - 1) * 0.95 + 0.999999)))
    return {
        "count": n,
        "mean_s": mean,
        "median_s": median,
        "p95_s": ordered[rank],
        "min_s": ordered[0],
        "max_s": ordered[-1],
    }


def _capture_audio(components: Any) -> tuple[Any, int]:
    print("[audio_capture] Recording one benchmark utterance -- speak now...")
    started = time.monotonic()
    audio, sample_rate = components.audio_input.capture()
    print(f"[audio_capture] OK ({time.monotonic() - started:.3f}s, sample_rate={sample_rate})")
    return audio, sample_rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    args = parser.parse_args()

    if args.warmups < 0 or args.runs <= 0:
        parser.error("--warmups must be >= 0 and --runs must be > 0")

    settings: Settings = get_settings()
    components = build_host_components(settings)
    store = components.store
    runner = components.runner
    if runner is None:
        raise RuntimeError("HostComponents.runner is not populated; Phase 5 runner wiring is missing.")

    store.ensure_user(
        args.user_id,
        declared_working_window_start="08:00",
        declared_working_window_end="22:00",
    )

    probes = {
        "stt": StageProbe("stt"),
        "intent": StageProbe("intent"),
        "context": StageProbe("context"),
        "reasoning": StageProbe("reasoning"),
        "tts": StageProbe("tts"),
        "policy": StageProbe("policy"),
    }

    restorers = [
        _install_ollama_probe(probes),
        _install_method_probe(store, "retrieve_context", probes["context"]),
        _install_method_probe(components.tts, "synthesize", probes["tts"]),
        _install_policy_probe(probes["policy"]),
    ]

    audio, sample_rate = _capture_audio(components)

    print("\nF6 baseline benchmark")
    print(f"[config] model={settings.llm_model!r}")
    print(f"[config] ollama_timeout_s={settings.ollama_timeout_s}")
    print(f"[config] session_timeout_seconds={settings.session_timeout_seconds}")
    print(f"[config] stt_device={settings.stt_device!r}")
    print(f"[config] stt_model_size={settings.stt_model_size!r}")
    print(f"[config] stt_compute_type={settings.stt_compute_type!r}")
    print(f"[experiment] warmups={args.warmups} measured_runs={args.runs}")
    print("[experiment] no F6 optimizations are applied by this script")

    records: list[RunRecord] = []

    for warmup in [True] * args.warmups + [False] * args.runs:
        run_index = sum(1 for record in records if not record.warmup) + 1 if not warmup else sum(1 for record in records if record.warmup) + 1
        for probe in probes.values():
            probe.reset()

        session_id = str(uuid.uuid4())
        session = SessionContext(
            session_id=session_id,
            user_id=args.user_id,
            started_monotonic=time.monotonic(),
        )

        started = time.monotonic()
        result = runner.run(session=session, audio=audio, sample_rate=sample_rate)
        total_observed = time.monotonic() - started

        stage = result.stage_timings_s
        row = RunRecord(
            run_index=run_index,
            warmup=warmup,
            trace_id=result.trace_id,
            intent=None,
            intent_confidence=None,
            affect_level=None,
            transcript=None,
            stt_s=float(stage.get("stt", 0.0)),
            intent_s=probes["intent"].elapsed_s,
            context_s=probes["context"].elapsed_s,
            reasoning_s=probes["reasoning"].elapsed_s,
            policy_s=probes["policy"].elapsed_s,
            affect_s=float(stage.get("affect", 0.0)),
            tts_s=probes["tts"].elapsed_s,
            graph_s=float(stage.get("dialogue_graph", 0.0)),
            interaction_to_tts_completion_s=result.latency_ms / 1000.0,
            llm_total_s=probes["intent"].elapsed_s + probes["reasoning"].elapsed_s,
            total_observed_s=total_observed,
            stage_timing_source="adapter-method probes + graph reducer timings",
        )
        # The runner result intentionally does not expose transcript/intent;
        # these are optional convenience fields for future script refinement.
        records.append(row)

        label = "warmup" if warmup else f"run {run_index}"
        print(
            f"[{label}] llm={row.llm_total_s:.3f}s "
            f"graph={row.graph_s:.3f}s tts={row.tts_s:.3f}s "
            f"interaction_to_tts_completion={row.interaction_to_tts_completion_s:.3f}s"
        )

    measured = [r for r in records if not r.warmup]
    summary = {
        field: _summary([getattr(r, field) for r in measured])
        for field in (
            "stt_s",
            "intent_s",
            "context_s",
            "reasoning_s",
            "policy_s",
            "affect_s",
            "tts_s",
            "graph_s",
            "llm_total_s",
            "interaction_to_tts_completion_s",
            "total_observed_s",
        )
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = EVIDENCE_DIR / f"f6_baseline_{timestamp}.txt"

    lines: list[str] = []
    lines.append("SYNCRO Host — F6 Baseline Measurement")
    lines.append("=" * 60)
    lines.append(f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Git revision: {_git_revision() or 'unknown'}")
    lines.append("")
    lines.append("PURPOSE")
    lines.append("-------")
    lines.append("Measure the current unmodified two-LLM WP-103 path before any F6 optimization.")
    lines.append("No num_predict, keep_alive, model split, timeout change, or STT-device change is applied.")
    lines.append("")
    lines.append("CURRENT CONFIGURATION")
    lines.append("---------------------")
    lines.append(f"llm_model: {settings.llm_model}")
    lines.append(f"ollama_url: {settings.ollama_url}")
    lines.append(f"ollama_timeout_s: {settings.ollama_timeout_s}")
    lines.append(f"session_timeout_seconds: {settings.session_timeout_seconds}")
    lines.append(f"stt_device: {settings.stt_device}")
    lines.append(f"stt_model_size: {settings.stt_model_size}")
    lines.append(f"stt_compute_type: {settings.stt_compute_type}")
    lines.append(f"stt_sample_rate_hz: {settings.audio_sample_rate_hz}")
    lines.append("")
    lines.append("EXPERIMENT")
    lines.append("----------")
    lines.append(f"Warm-up runs: {args.warmups}")
    lines.append(f"Measured runs: {args.runs}")
    lines.append("Same captured audio replayed across runs: yes")
    lines.append("Production F6 changes applied: none")
    lines.append("")
    lines.append("MEASUREMENT LIMITATIONS")
    lines.append("-----------------------")
    for item in [
        "The current Piper adapter is blocking; TTS onset is not exposed, so interaction_to_tts_completion_s is the observable latency proxy.",
        "Affect timing comes from the Phase 1 reducer-backed graph timing field.",
        "STT, intent, context, reasoning, policy, and TTS timings are observed by wrapping existing runtime boundaries in this script only.",
        "The benchmark replays one captured audio sample across measured runs for repeatability; audio capture time is reported separately and is not included in interaction timing.",
        "The current adapters do not expose Ollama token/eval metrics through their contracts, so this baseline records wall-clock stage latency only.",
    ]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("SUMMARY (MEASURED RUNS)")
    lines.append("=======================")
    for field, result in summary.items():
        lines.append(
            f"{field}: count={result['count']}, mean={result['mean_s']}, "
            f"median={result['median_s']}, p95={result['p95_s']}, "
            f"min={result['min_s']}, max={result['max_s']}"
        )
    lines.append("")

    lines.append("PER-RUN RESULTS")
    lines.append("===============")
    headers = [
        "run", "kind", "stt_s", "intent_s", "context_s", "reasoning_s",
        "policy_s", "affect_s", "tts_s", "graph_s", "llm_total_s",
        "interaction_to_tts_completion_s", "total_observed_s", "trace_id"
    ]
    lines.append(" | ".join(headers))
    lines.append("-" * 60)
    for record in records:
        values = [
            str(record.run_index),
            "warmup" if record.warmup else "measured",
            f"{record.stt_s:.6f}", f"{record.intent_s:.6f}", f"{record.context_s:.6f}",
            f"{record.reasoning_s:.6f}", f"{record.policy_s:.6f}", f"{record.affect_s:.6f}",
            f"{record.tts_s:.6f}", f"{record.graph_s:.6f}", f"{record.llm_total_s:.6f}",
            f"{record.interaction_to_tts_completion_s:.6f}", f"{record.total_observed_s:.6f}",
            record.trace_id,
        ]
        lines.append(" | ".join(values))
    lines.append("")
    lines.append("STAGE TIMING SOURCE")
    lines.append("===================")
    lines.append("adapter-method probes + graph reducer timings")
    lines.append("")
    lines.append("BASELINE USE")
    lines.append("=============")
    lines.append("Use this TXT evidence as the before-measurement baseline for Phase 9 F6 decisions.")
    lines.append("Do not treat it as optimized performance evidence; no F6 optimization is applied here.")

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nF6 baseline complete")
    print(f"[evidence] TXT:  {txt_path}")
    print("[evidence] Use these files as the before-measurement baseline for Phase 9 decisions.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
