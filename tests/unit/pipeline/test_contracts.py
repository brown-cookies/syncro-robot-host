from __future__ import annotations
from typing import get_args

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pipeline.contracts import (
    ALLOWED_INTENTS,
    AddTaskSlots,
    DegradedTraceRecord,
    DecisionTraceRecord,
    DismissReminderSlots,
    ExecutionOutcome,
    RescheduleTaskSlots,
    ResponsePayload,
    SnoozeReminderSlots,
)


def base_trace(**overrides):
    """Perform the base trace operation required by the project."""
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
    """Verify that response payload matches section 8 1 shape."""
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
    """Verify that decision trace matches section 8 3 shape."""
    trace = DecisionTraceRecord(**base_trace()).model_dump(mode="json")
    assert set(trace) == {
        "trace_id", "session_id", "user_id", "timestamp", "intent",
        "intent_confidence", "retrieved_context_ids", "affect_level",
        "deadline_proximity", "policy_rule", "action_taken", "lead_time_min",
        "reminder_outcome", "degradation_reason", "network_event",
        "latency_ms", "latency_basis",
    }


def test_non_policy_trace_requires_na_for_both_fields():
    """Verify that non policy trace requires na for both fields."""
    with pytest.raises(ValueError):
        DecisionTraceRecord(**base_trace(deadline_proximity="imminent"))


def test_invalid_policy_enum_is_rejected():
    """Verify that invalid policy enum is rejected."""
    with pytest.raises(ValueError):
        DecisionTraceRecord(**base_trace(policy_rule="R9",
                            deadline_proximity="imminent"))


def test_policy_trace_accepts_each_spec_rule():
    """Verify that policy trace accepts each spec rule."""
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
                action_taken="deliver" if rule in {
                    "R1", "R3", "R5"} else "defer",
                reminder_outcome="pending",
            )
        )


def test_degraded_trace_allows_missing_normal_interaction_fields():
    record = DegradedTraceRecord(
        trace_id=uuid4(),
        session_id="session-1",
        user_id="user-1",
        timestamp=datetime.now(timezone.utc),
        degradation_reason="pipeline_failure",
    )
    dumped = record.model_dump(mode="json")
    assert dumped["intent"] is None
    assert dumped["intent_confidence"] is None
    assert dumped["affect_level"] is None
    assert dumped["policy_rule"] == "n/a"
    assert dumped["deadline_proximity"] == "n/a"
    assert dumped["action_taken"] == "n/a"
    assert dumped["reminder_outcome"] == "n/a"


def test_no_interaction_degradation_rejects_non_null_intent():
    with pytest.raises(ValueError, match="cannot carry an intent"):
        DegradedTraceRecord(
            trace_id=uuid4(),
            session_id="session-1",
            user_id="user-1",
            timestamp=datetime.now(timezone.utc),
            intent="ask_status",
            degradation_reason="pipeline_failure",
        )


def test_degraded_trace_allows_standalone_event_without_session_id():
    record = DegradedTraceRecord(
        trace_id=uuid4(),
        session_id=None,
        user_id="user-1",
        timestamp=datetime.now(timezone.utc),
        degradation_reason="queue_overflow",
    )
    assert record.session_id is None


def test_normal_decision_trace_still_rejects_missing_interaction_fields():
    with pytest.raises(ValueError):
        DecisionTraceRecord(**base_trace(intent=None))


# --- Phase 17 Phase 1: ExecutableIntent / slots / ExecutionOutcome ---------


from pipeline.contracts import ExecutableIntent  # noqa: E402  (grouped with the above)


def test_executable_intents_are_closed_and_a_subset_of_allowed_intents():
    """ExecutableIntent is a strict, closed subset of the classifier-level
    ALLOWED_INTENTS -- request_summary/request_break/ask_status never reach
    the executor."""
    executable = set(get_args(ExecutableIntent))
    assert executable == {
        "add_task", "reschedule_task", "snooze_reminder", "dismiss_reminder",
    }
    assert executable <= ALLOWED_INTENTS
    assert executable != ALLOWED_INTENTS


def test_add_task_slots_requires_title_and_defaults_priority():
    slots = AddTaskSlots(title="Buy milk")
    assert slots.priority == "normal"
    assert slots.deadline is None
    with pytest.raises(ValidationError):
        AddTaskSlots(title="")


def test_reschedule_task_slots_requires_explicit_task_id_no_fallback():
    """No "most recent task" default exists -- task_id is a required field
    with no default, so a caller that can't name a task cannot construct
    valid slots at all."""
    slots = RescheduleTaskSlots(
        task_id="task-1", new_deadline=datetime.now(timezone.utc)
    )
    assert slots.task_id == "task-1"
    with pytest.raises(ValidationError):
        RescheduleTaskSlots(new_deadline=datetime.now(
            timezone.utc))  # type: ignore


def test_snooze_reminder_slots_rejects_non_positive_minutes():
    SnoozeReminderSlots(reference_trace_id="trace-1", snooze_minutes=5)
    with pytest.raises(ValidationError):
        SnoozeReminderSlots(reference_trace_id="trace-1", snooze_minutes=0)
    with pytest.raises(ValidationError):
        SnoozeReminderSlots(reference_trace_id="trace-1", snooze_minutes=-5)


def test_reminder_slots_reject_missing_reference():
    """No "most recent pending row for user" fallback -- the reference is a
    required field, not something the slot model can default its way out
    of."""
    with pytest.raises(ValidationError):
        SnoozeReminderSlots(snooze_minutes=5)  # type: ignore
    with pytest.raises(ValidationError):
        DismissReminderSlots()  # type: ignore
    DismissReminderSlots(reference_trace_id="trace-1")


def test_execution_outcome_succeeded_requires_target_id_and_no_error_code():
    ExecutionOutcome(
        succeeded=True,
        intent="dismiss_reminder",
        target_id="trace-1",
        detail="reminder dismissed",
    )
    with pytest.raises(ValidationError, match="must carry a target_id"):
        ExecutionOutcome(succeeded=True, intent="dismiss_reminder", detail="x")
    with pytest.raises(ValidationError, match="must not carry an error_code"):
        ExecutionOutcome(
            succeeded=True,
            intent="dismiss_reminder",
            target_id="trace-1",
            error_code="reminder_not_found",
            detail="x",
        )


def test_execution_outcome_failed_requires_error_code_and_no_target_id():
    ExecutionOutcome(
        succeeded=False,
        intent="dismiss_reminder",
        error_code="reminder_not_found",
        detail="no pending reminder for that reference",
    )
    with pytest.raises(ValidationError, match="must carry an error_code"):
        ExecutionOutcome(
            succeeded=False, intent="dismiss_reminder", detail="x")
    with pytest.raises(ValidationError, match="must not carry a target_id"):
        ExecutionOutcome(
            succeeded=False,
            intent="dismiss_reminder",
            target_id="trace-1",
            error_code="reminder_not_found",
            detail="x",
        )


def test_execution_outcome_snooze_minutes_reaches_the_outcome():
    """snooze_minutes must survive on a succeeded snooze_reminder outcome so
    Phase 2's EMA update isn't discarded (plan Phase 2 test requirement)."""
    outcome = ExecutionOutcome(
        succeeded=True,
        intent="snooze_reminder",
        target_id="trace-1",
        snooze_minutes=10,
        detail="snoozed for 10 minutes",
    )
    assert outcome.snooze_minutes == 10
    with pytest.raises(ValidationError, match="must carry snooze_minutes"):
        ExecutionOutcome(
            succeeded=True,
            intent="snooze_reminder",
            target_id="trace-1",
            detail="x",
        )


def test_execution_outcome_snooze_minutes_rejected_off_snooze_intent():
    with pytest.raises(ValidationError, match="only valid for a snooze_reminder"):
        ExecutionOutcome(
            succeeded=True,
            intent="dismiss_reminder",
            target_id="trace-1",
            snooze_minutes=5,
            detail="x",
        )


def test_execution_outcome_rejects_unknown_error_code():
    with pytest.raises(ValidationError):
        ExecutionOutcome(
            succeeded=False,
            intent="add_task",
            error_code="not_a_real_code",  # type: ignore
            detail="x",
        )
