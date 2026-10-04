"""OBS-LOG item 4: the failure/degradation scenario runner and what it asserts.

Offline mode drives the real graph + runner + FileSink + SQLite with injected
faults. The ``--real`` rig is exercised only for its wiring (which setting or
fault each scenario produces); the real models are not run here.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("langgraph")

from scripts import run_failure_scenarios as rfs
from scripts import show_trace

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scenario", rfs.SCENARIOS, ids=lambda s: s.name)
def test_every_scenario_leaves_a_trace_that_passes_all_its_checks(scenario):
    out = io.StringIO()
    assert rfs.run_scenario(scenario, real=False, wav_audio=None, out=out), out.getvalue()


def test_main_runs_all_scenarios_and_exits_zero(capsys):
    assert rfs.main([]) == 0
    assert "[FAIL]" not in capsys.readouterr().out


def test_main_rejects_an_unknown_scenario_name():
    with pytest.raises(SystemExit):
        rfs.main(["no_such_scenario"])


def test_a_trace_with_two_trace_ids_is_reported_as_a_failure():
    ev = lambda tid, i: {  # noqa: E731
        "trace_id": tid, "event_id": str(i), "parent_event_id": None, "component": "runner",
        "event_type": "interaction_started", "severity": "INFO", "status": "started",
        "duration_ms": None, "metadata": {}, "error": None,
    }
    checks = rfs.invariant_checks([ev("a", 1), ev("b", 2)], [{"trace_id": "a", "degradation_reason": None}])
    assert not dict((m, ok) for ok, m in checks)["one trace_id across all 2 events (2 found)"]


def test_a_started_stage_without_a_terminal_event_is_reported():
    started = {
        "trace_id": "a", "event_id": "s1", "parent_event_id": None, "component": "stt",
        "event_type": "stage_started", "severity": "INFO", "status": "started",
        "duration_ms": None, "metadata": {}, "error": None,
    }
    checks = rfs.invariant_checks([started], [{"trace_id": "a", "degradation_reason": None}])
    assert any(not ok and "stt stage_started has exactly one terminal" in m for ok, m in checks)


# --- --real wiring (no real models are loaded) --------------------------------

@pytest.fixture
def fake_bootstrap(monkeypatch, tmp_path):
    captured = {}

    def fake_build(settings, *, affect_detector=None):
        captured["settings"], captured["affect"] = settings, affect_detector
        return SimpleNamespace(
            runner=SimpleNamespace(close=lambda: None), emitter=SimpleNamespace(close=lambda: None),
            store=SimpleNamespace(ensure_user=lambda user: None),
        )

    monkeypatch.setattr("composition.bootstrap.build_host_components", fake_build)
    return captured


def _scenario(name):
    return next(s for s in rfs.SCENARIOS if s.name == name)


def test_real_rig_points_ollama_at_a_dead_port(fake_bootstrap, tmp_path):
    speech = np.zeros(10, dtype=np.float32)
    rfs.build_real_rig(_scenario("ollama_down_intent"), tmp_path, speech)
    assert fake_bootstrap["settings"].ollama_url == "http://127.0.0.1:9"


def test_real_rig_forces_a_tiny_tts_timeout(fake_bootstrap, tmp_path):
    rfs.build_real_rig(_scenario("tts_timeout"), tmp_path, np.zeros(10, dtype=np.float32))
    assert fake_bootstrap["settings"].tts_timeout_s == 0.001


def test_real_rig_injects_a_failing_affect_detector(fake_bootstrap, tmp_path):
    rfs.build_real_rig(_scenario("affect_fallback"), tmp_path, np.zeros(10, dtype=np.float32))
    assert isinstance(fake_bootstrap["affect"], rfs.BrokenAffect)


def test_real_rig_uses_silence_for_the_empty_transcript_scenario(fake_bootstrap, tmp_path):
    rig = rfs.build_real_rig(_scenario("empty_transcript"), tmp_path, None)  # no WAV needed
    assert rig.audio.size > 0 and not rig.audio.any()


def test_real_rig_needs_a_wav_for_scenarios_that_need_speech(fake_bootstrap, tmp_path):
    with pytest.raises(SystemExit):
        rfs.build_real_rig(_scenario("tts_timeout"), tmp_path, None)


def test_real_rig_writes_log_and_db_into_the_temp_dir_not_the_working_dir(fake_bootstrap, tmp_path):
    rfs.build_real_rig(_scenario("baseline"), tmp_path, np.zeros(10, dtype=np.float32))
    s = fake_bootstrap["settings"]
    assert s.log_file_path.startswith(str(tmp_path)) and s.db_path.startswith(str(tmp_path))
    assert s.log_output == "file" and s.log_include_text is False


# --- show_trace outcome labels ---------------------------------------------------

def _row(trace, event_type, severity="INFO"):
    return {"trace_id": trace, "timestamp": "2026-10-04T10:00:00+00:00", "session_id": "s",
            "event_type": event_type, "severity": severity}


def _outcome(tmp_path, *events):
    import json
    path = tmp_path / "log.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return show_trace.list_traces(path)[0]["outcome"]


def test_show_trace_outcome_ok_degraded_failed_incomplete(tmp_path):
    assert _outcome(tmp_path, _row("t", "interaction_completed")) == "ok"
    # a recovered ERROR (affect fallback) on a completed interaction is degraded, not failed
    assert _outcome(tmp_path, _row("t", "model_inference_failed", "ERROR"),
                    _row("t", "interaction_completed")) == "degraded"
    assert _outcome(tmp_path, _row("t", "degradation_applied", "WARNING"),
                    _row("t", "interaction_completed")) == "degraded"
    assert _outcome(tmp_path, _row("t", "stage_failed", "ERROR"),
                    _row("t", "interaction_failed", "ERROR")) == "FAILED"
    assert _outcome(tmp_path, _row("t", "interaction_started")) == "incomplete"
