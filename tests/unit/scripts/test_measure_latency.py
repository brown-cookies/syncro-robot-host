"""Step 4: the latency table math and the honest status line."""

import pytest

from scripts.measure_latency import build_row, render_table, status_line


def _timings(**overrides):
    base = {
        "stt": 1.3, "intent": 0.2, "context": 0.1, "llm": 2.6,
        "affect": 0.8, "policy": 0.05, "output": 0.01,
        "dialogue_graph": 4.3, "tts": 0.25,
    }
    base.update(overrides)
    return base


def test_columns_sum_to_total_and_split_at_the_right_stages():
    # 5.25 s mic window + 4.3 s graph + 0.25 s tts = 9.8 s total
    row = build_row(1, total_ms=9800.0, capture_s=5.25, stage_timings_s=_timings(), basis="host_observed_only")

    # wake->intent = pre-graph (5.25 s) + stt + intent
    assert row.wake_to_intent_ms == pytest.approx(5250 + 1300 + 200)
    # intent->policy = context + llm + policy
    assert row.intent_to_policy_ms == pytest.approx(100 + 2600 + 50)
    assert row.wake_to_intent_ms + row.intent_to_policy_ms + row.policy_to_tts_ms == pytest.approx(9800.0)
    assert row.llm_ms == pytest.approx(2600.0)
    assert row.post_capture_ms == pytest.approx(9800 - 5250)


def test_15_sep_evidence_total_is_capture_plus_graph_plus_tts():
    """The 13.7 s host_observed_only figure is not cold-start mystery time: it
    is the 5.25 s mic window + 8.23 s graph + 0.24 s TTS."""
    row = build_row(
        1, total_ms=13727.8, capture_s=5.254,
        stage_timings_s={"dialogue_graph": 8.2295, "tts": 0.2436, "stt": 1.3293, "affect": 0.7632},
        basis="host_observed_only",
    )
    assert row.wake_to_intent_ms - 1329.3 == pytest.approx(5254, abs=5)


def test_status_is_computed_from_the_observed_value_not_assumed():
    assert "Status: not achieved" in status_line(9800.0)
    assert "Status: achieved" in status_line(2900.0)
    assert "Status: not achieved" not in status_line(3000.0)


def test_table_discloses_a_missed_budget_and_the_clock_basis():
    rows = [build_row(i, total_ms=9800.0, capture_s=5.25, stage_timings_s=_timings(), basis="host_observed_only") for i in (1, 2, 3)]
    text = render_table(rows)
    assert "Status: not achieved" in text
    assert "host_observed_only" in text
    assert "Run 0 (warm-up) discarded" in text
    assert "| run | wake->intent | intent->policy | policy->TTS | total |" in text


def test_table_says_achieved_only_when_it_is():
    rows = [build_row(1, total_ms=2500.0, capture_s=0.0, stage_timings_s={"dialogue_graph": 2.3, "tts": 0.2}, basis="wake_word_to_tts")]
    text = render_table(rows)
    assert "Status: achieved" in text
    assert "not achieved" not in text
    assert "Explanation: the budget is not met" not in text


def test_no_runs_is_an_error_not_a_fake_table():
    with pytest.raises(ValueError):
        render_table([])
