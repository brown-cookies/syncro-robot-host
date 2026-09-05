"""WP-103 output assembly and decision-trace capture."""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from typing import cast
from uuid import uuid4

from pipeline.contracts import (
    ActionTaken,
    AffectLevel,
    DeadlineProximity,
    DecisionTraceRecord,
    PolicyRule,
    ReminderOutcome,
    ResponsePayload,
)
from pipeline.state import DialogueState


def make_output_node(store):
    """Create the output graph node with its injected speech synthesizer."""
    def output_node(state: DialogueState) -> DialogueState:
        """Prepare the final response output from the completed dialogue state."""
        session_id = state.get("session_id")
        user_id = state.get("user_id")
        final_response = state.get("final_response")
        intent = state.get("intent")
        intent_confidence = state.get("intent_confidence")

        missing = [
            name
            for name, value in (
                ("session_id", session_id),
                ("user_id", user_id),
                ("final_response", final_response),
                ("intent", intent),
                ("intent_confidence", intent_confidence),
            )
            if value is None
        ]
        if missing:
            raise RuntimeError(
                "Node output assembly missing required DialogueState keys: "
                + ", ".join(missing)
            )

        # The checks above narrow these values for both runtime safety and
        # static type checkers such as Pylance.
        if not isinstance(session_id, str):
            raise TypeError("session_id must be a string")
        if not isinstance(user_id, str):
            raise TypeError("user_id must be a string")
        if not isinstance(final_response, str) or not final_response:
            raise TypeError("final_response must be a non-empty string")
        if not isinstance(intent, str) or not intent:
            raise TypeError("intent must be a non-empty string")
        if not isinstance(intent_confidence, (int, float)):
            raise TypeError("intent_confidence must be numeric")

        trace_id = uuid4()

        policy_rule_raw = state.get("policy_rule", "n/a")
        if policy_rule_raw not in {"R1", "R2", "R3", "R4", "R5", "n/a"}:
            raise ValueError(f"Invalid policy_rule: {policy_rule_raw!r}")
        policy_rule = cast(PolicyRule, policy_rule_raw)

        deadline_proximity_raw = state.get("deadline_proximity", "n/a")
        if deadline_proximity_raw not in {"imminent", "not_imminent", "n/a"}:
            raise ValueError(
                f"Invalid deadline_proximity: {deadline_proximity_raw!r}"
            )
        deadline_proximity = cast(DeadlineProximity, deadline_proximity_raw)

        if policy_rule == "n/a":
            deadline_proximity = "n/a"

        action_taken_raw = state.get("action_taken", "deliver")
        if action_taken_raw not in {
            "deliver", "defer", "soften", "break_prompt", "suppress"
        }:
            raise ValueError(f"Invalid action_taken: {action_taken_raw!r}")
        action_taken = cast(ActionTaken, action_taken_raw)

        affect_level_raw = state.get("affect_level")
        if affect_level_raw not in {"Low", "Moderate", "High"}:
            raise ValueError(
                "Missing or invalid affect_level; Node 4 must consume the parallel detector result."
            )
        affect_level = cast(AffectLevel, affect_level_raw)

        reminder_outcome_raw = state.get("reminder_outcome", "n/a")
        if reminder_outcome_raw not in {
            "accepted", "snoozed", "delivery_miss", "pending", "n/a"
        }:
            raise ValueError(
                f"Invalid reminder_outcome: {reminder_outcome_raw!r}"
            )
        reminder_outcome = cast(ReminderOutcome, reminder_outcome_raw)

        lead_time_raw = state.get("lead_time_min", 15.0)
        if not isinstance(lead_time_raw, (int, float)):
            raise TypeError("lead_time_min must be numeric")
        lead_time_min = float(lead_time_raw)

        started_monotonic = state.get("started_monotonic")
        if not isinstance(started_monotonic, (int, float)):
            started_monotonic = monotonic()

        payload = ResponsePayload(
            session_id=session_id,
            tts_text=final_response,
            state_tag=(
                "break_prompt"
                if action_taken == "break_prompt"
                else "deferred"
                if action_taken == "defer"
                else "speaking"
            ),
            policy_rule=policy_rule,
            lead_time_min=lead_time_min,
        )

        trace = DecisionTraceRecord(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc),
            intent=intent,
            intent_confidence=float(intent_confidence),
            retrieved_context_ids=list(state.get("retrieved_context_ids", [])),
            affect_level=affect_level,
            deadline_proximity=deadline_proximity,
            policy_rule=policy_rule,
            action_taken=action_taken,
            lead_time_min=lead_time_min,
            reminder_outcome=reminder_outcome,
            degradation_reason=None,
            network_event=None,
            latency_ms=max(
                0.0,
                (monotonic() - float(started_monotonic)) * 1000.0,
            ),
            latency_basis="host_observed_only",
        )
        store.save_decision_trace(trace.model_dump(mode="json"))

        return {
            "trace_id": str(trace_id),
            "response_payload": payload.model_dump(mode="json"),
        }

    return output_node
