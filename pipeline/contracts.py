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
ReminderOutcome = Literal["accepted", "snoozed",
                          "delivery_miss", "pending", "n/a"]
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
    "affect_detector_failure",
    "pipeline_failure",
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


class DegradedTraceRecord(_Contract):
    """Decision-trace record for interactions that never produced a normal turn."""

    trace_id: UUID
    session_id: str | None
    user_id: str
    timestamp: datetime
    intent: str | None = None
    intent_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    retrieved_context_ids: list[str] | None = None
    affect_level: Literal["Low", "Moderate", "High"] | None = None
    deadline_proximity: Literal["n/a"] = "n/a"
    policy_rule: Literal["n/a"] = "n/a"
    action_taken: Literal["n/a"] = "n/a"
    lead_time_min: float | None = None
    reminder_outcome: Literal["n/a"] = "n/a"
    degradation_reason: DegradationReason
    network_event: NetworkEvent | None = None
    latency_ms: float = Field(default=0.0, ge=0.0)
    latency_basis: LatencyBasis = "host_observed_only"

    @model_validator(mode="after")
    def validate_degraded_fields(self) -> "DegradedTraceRecord":
        """Enforce the Phase 8 degraded-record contract."""
        no_interaction_reasons = {
            "session_timeout",
            "queue_overflow",
            "pipeline_failure",
        }
        if self.degradation_reason in no_interaction_reasons and self.intent is not None:
            raise ValueError(
                "degraded traces with no-interaction reasons cannot carry an intent"
            )
        if self.degradation_reason in no_interaction_reasons:
            if self.policy_rule != "n/a" or self.deadline_proximity != "n/a":
                raise ValueError(
                    "degraded traces cannot carry a policy-domain result")
        return self


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


# --- Phase 17: Action Execution Boundary -----------------------------------
#
# The four intents below are the only ones an `ActionExecutor` (Phase 3) may
# ever mutate storage for. This is a strict subset of ALLOWED_INTENTS (the
# classifier-level contract, unchanged): `request_summary`, `request_break`,
# and `ask_status` are read-only/conversational and never reach the executor.
ExecutableIntent = Literal[
    "add_task", "reschedule_task", "snooze_reminder", "dismiss_reminder"
]

# Centralized error-code vocabulary (plan Phase 1). Anything the executor or
# its storage calls can reject with gets one of these -- no ad-hoc strings.
ExecutionErrorCode = Literal[
    "task_not_found",
    "ambiguous_task",
    "reminder_not_found",
    "reminder_not_pending",
    "invalid_slots",
]


class _ExecutableSlots(_Contract):
    """Shared base for the four executable intents' slot shapes."""


class AddTaskSlots(_ExecutableSlots):
    """Slots for ``add_task``. No target resolution needed -- this creates a
    new row; `task_id` is generated at the storage boundary (Phase 2), never
    supplied here."""

    title: str = Field(min_length=1)
    deadline: datetime | None = None
    notes: str | None = None
    priority: Literal["low", "normal", "high"] = "normal"


class RescheduleTaskSlots(_ExecutableSlots):
    """Resolved slots for ``reschedule_task``.

    The classifier produces the raw ``task_reference`` string. Phase 3's
    executor resolves that reference against Node 2's pre-mutation context
    and constructs this model only after it has one unambiguous ``task_id``.
    There is deliberately no "most recent task" fallback.
    """

    task_id: str = Field(min_length=1)
    new_deadline: datetime


class _ReminderReferenceSlots(_ExecutableSlots):
    """Shared shape for the two reminder-outcome intents.

    `reference_trace_id` is the resolved reminder this turn is responding
    to -- the earlier `decision_trace` row whose `reminder_outcome` is
    `"pending"`. Phase 1 defines the *shape* only; nothing in this codebase
    populates it from a live utterance yet (see the Phase 1 plan's "Must
    resolve" note: SPEC 7.3's `start_audio` schema carries no such field
    today, and no phase currently assigns the wire-plumbing work that would
    fill it in). Callers before that plumbing exists must supply it directly
    (e.g. from a seeded row, per the Phase 2 plan's `seed_wp103.py` pattern).
    There is deliberately no "most recent pending row for user" fallback --
    that heuristic is explicitly rejected by the plan.
    """

    reference_trace_id: str = Field(min_length=1)


class SnoozeReminderSlots(_ReminderReferenceSlots):
    """Slots for ``snooze_reminder``. `snooze_minutes` is the intent's own
    extracted slot (`adapters/llm/intent_classifier.py` already requires a
    positive integer here); `s` in SPEC §11.2's `L_hat = L - s`."""

    snooze_minutes: int = Field(gt=0)


class DismissReminderSlots(_ReminderReferenceSlots):
    """Slots for ``dismiss_reminder``. No additional fields beyond the
    resolved reminder reference."""


ExecutableSlots = (
    AddTaskSlots | RescheduleTaskSlots | SnoozeReminderSlots | DismissReminderSlots
)


class ExecutionOutcome(_Contract):
    """What `ActionExecutor.execute` (Phase 3) returns for every executable
    intent -- succeeded or failed, never partial, never silent.

    This is `DialogueState["execution_outcome"]`'s shape (see `state.py`);
    it is never persisted as new `decision_trace` columns (standing
    constraint: no `proposed_action`/`execution_status`/
    `execution_error_code` columns without an explicit SPEC §8.3/§9
    amendment) -- it lives in `DialogueState` only, for Node 3/Node 4 to
    read within the same turn.
    """

    succeeded: bool
    intent: ExecutableIntent
    target_id: str | None = None
    error_code: ExecutionErrorCode | None = None
    detail: str = Field(min_length=1)
    snooze_minutes: int | None = None

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> "ExecutionOutcome":
        """Enforce succeeded/failed are mutually exclusive in their fields.

        A failure must carry an `error_code` and must not carry a
        `target_id` (nothing was resolved/mutated to point at); a success
        must carry a `target_id` and must not carry an `error_code`.
        `snooze_minutes` is only meaningful for a succeeded `snooze_reminder`
        outcome -- carried through so Phase 2's EMA update isn't discarded.
        """
        if self.succeeded:
            if self.error_code is not None:
                raise ValueError(
                    "a succeeded outcome must not carry an error_code")
            if self.target_id is None:
                raise ValueError("a succeeded outcome must carry a target_id")
        else:
            if self.error_code is None:
                raise ValueError("a failed outcome must carry an error_code")
            if self.target_id is not None:
                raise ValueError("a failed outcome must not carry a target_id")
        if self.snooze_minutes is not None and self.intent != "snooze_reminder":
            raise ValueError(
                "snooze_minutes is only valid for a snooze_reminder outcome"
            )
        if (
            self.succeeded
            and self.intent == "snooze_reminder"
            and self.snooze_minutes is None
        ):
            raise ValueError(
                "a succeeded snooze_reminder outcome must carry snooze_minutes"
            )
        return self
