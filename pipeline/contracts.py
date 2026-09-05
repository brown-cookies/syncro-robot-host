"""WP-103 wire/data contracts defined by techdocs/SPEC.md Section 8."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

StateTag = Literal["idle", "listening", "speaking", "break_prompt", "deferred"]
AffectLevel = Literal["Low", "Moderate", "High"]
PolicyRule = Literal["R1", "R2", "R3", "R4", "R5", "n/a"]
DeadlineProximity = Literal["imminent", "not_imminent", "n/a"]
ActionTaken = Literal["deliver", "defer", "soften", "break_prompt", "suppress"]
ReminderOutcome = Literal["accepted", "snoozed", "delivery_miss", "pending", "n/a"]
LatencyBasis = Literal["wake_word_to_tts", "host_observed_only"]
DegradationReason = Literal[
    "mute_engaged",
    "audio_device_unavailable",
    "tts_timeout",
    "playback_error",
    "playback_underrun",
    "delivery_failed",
    "session_timeout",
    "activity_unavailable",
    "queue_overflow",
]
NetworkEvent = Literal[
    "connect_attempt",
    "connect_success",
    "connect_failed",
    "host_disconnected",
    "reconnect_success",
]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponsePayload(_Contract):
    """Exact Section 8.1 `response` message body."""

    type: Literal["response"] = "response"
    session_id: str
    tts_text: str = Field(min_length=1)
    state_tag: StateTag | None = None
    policy_rule: PolicyRule
    lead_time_min: float


class DecisionTraceRecord(_Contract):
    """Exact Section 8.3 decision-trace record."""

    trace_id: UUID
    session_id: str
    user_id: str
    timestamp: datetime
    intent: str
    intent_confidence: float = Field(ge=0.0, le=1.0)
    retrieved_context_ids: list[str]
    affect_level: Literal["Low", "Moderate", "High"]
    deadline_proximity: DeadlineProximity
    policy_rule: PolicyRule
    action_taken: ActionTaken
    lead_time_min: float
    reminder_outcome: ReminderOutcome
    degradation_reason: DegradationReason | None = None
    network_event: NetworkEvent | None = None
    latency_ms: float = Field(ge=0.0)
    latency_basis: LatencyBasis

    @model_validator(mode="after")
    def validate_policy_domain(self) -> "DecisionTraceRecord":
        """Validate that a policy trace uses only the allowed policy-domain values."""
        if self.policy_rule == "n/a":
            if self.deadline_proximity != "n/a":
                raise ValueError(
                    "deadline_proximity must be n/a when policy_rule is n/a"
                )
        elif self.deadline_proximity == "n/a":
            raise ValueError(
                "deadline_proximity cannot be n/a when policy_rule is R1-R5"
            )
        return self


ALLOWED_INTENTS = frozenset({
    "add_task",
    "reschedule_task",
    "request_summary",
    "request_break",
    "dismiss_reminder",
    "snooze_reminder",
    "ask_status",
})
