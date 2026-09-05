from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from pipeline.contracts import DecisionTraceRecord, ResponsePayload


def base_trace(**overrides):
    record = {
        "trace_id": uuid4(),
        "session_id": "session-1",
        "user_id": "user-1",
        "timestamp": datetime.now(timezone.utc),
        "intent": "ask_status",
        "intent_confidence": 0.91,
        "retrieved_context_ids": ["task-1", "routine-1"],
        "affect_level": "Low",
        "deadline_proximity": "n/a",
        "policy_rule": "n/a",
        "action_taken": "deliver",
        "lead_time_min": 15,
        "reminder_outcome": "n/a",
        "degradation_reason": None,
        "network_event": None,
        "latency_ms": 123.4,
        "latency_basis": "host_observed_only",
    }
    record.update(overrides)
    return record


def test_response_payload_matches_section_8_1_shape():
    payload = ResponsePayload(
        session_id="session-1",
        tts_text="Done.",
        state_tag="speaking",
        policy_rule="n/a",
        lead_time_min=15,
    ).model_dump(mode="json")
    assert set(payload) == {
        "type", "session_id", "tts_text", "state_tag", "policy_rule", "lead_time_min"
    }
    assert payload["type"] == "response"


def test_decision_trace_matches_section_8_3_shape():
    trace = DecisionTraceRecord(**base_trace()).model_dump(mode="json")
    assert set(trace) == {
        "trace_id", "session_id", "user_id", "timestamp", "intent",
        "intent_confidence", "retrieved_context_ids", "affect_level",
        "deadline_proximity", "policy_rule", "action_taken", "lead_time_min",
        "reminder_outcome", "degradation_reason", "network_event",
        "latency_ms", "latency_basis",
    }


def test_non_policy_trace_requires_na_for_both_fields():
    with pytest.raises(ValueError):
        DecisionTraceRecord(**base_trace(deadline_proximity="imminent"))


def test_invalid_policy_enum_is_rejected():
    with pytest.raises(ValueError):
        DecisionTraceRecord(**base_trace(policy_rule="R9", deadline_proximity="imminent"))


def test_policy_trace_accepts_each_spec_rule():
    cases = {
        "R1": "not_imminent",
        "R2": "not_imminent",
        "R3": "imminent",
        "R4": "not_imminent",
        "R5": "imminent",
    }
    for rule, proximity in cases.items():
        DecisionTraceRecord(
            **base_trace(
                intent="dismiss_reminder",
                policy_rule=rule,
                deadline_proximity=proximity,
                action_taken="deliver" if rule in {"R1", "R3", "R5"} else "defer",
                reminder_outcome="pending",
            )
        )
