"""Typed state carried through the WP-103 dialogue graph."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge_stage_timings(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    """Combine per-stage timing dicts written by parallel graph branches.

    LangGraph calls this reducer with the state's current value as ``left`` and each
    node's returned partial update as ``right`` within the same superstep, so this must
    be commutative and must not mutate either argument.
    """
    return {**left, **right}


class DialogueState(TypedDict, total=False):
    # Unique identifier for the current interaction/session.
    # Used to correlate the graph execution, response, and trace record.
    session_id: str

    # Identifier of the participant/user associated with this interaction.
    # Used for user-scoped context and storage operations.
    user_id: str

    # Raw input audio for the current utterance.
    # Consumed by the STT and affect-analysis branches.
    audio: Any

    # Sample rate of the input audio in Hz.
    # Describes how the audio in `audio` should be interpreted.
    sample_rate: int

    # Edge/robot timestamp indicating when the wake word was detected.
    # Used with clock synchronization to measure wake-word-to-response latency.
    wake_word_detected_at: int

    # Text transcription produced from the input audio.
    # This becomes the natural-language input for intent classification and reasoning.
    transcript: str

    # Classified user intent.
    # Identifies what the user is trying to do, such as `add_task`,
    # `snooze_reminder`, `ask_status`, or `request_break`.
    intent: str

    # Confidence score assigned to the classified intent.
    # Low confidence can route the interaction to clarification before execution.
    intent_confidence: float

    # Structured information extracted from the user's utterance.
    # Contains the raw slots needed to interpret or execute the selected intent.
    # The executor is responsible for resolving references into authoritative IDs.
    slots: dict[str, Any]

    # Context retrieved from storage for this interaction.
    # Represents the state of the user's tasks/routines as known before mutation.
    context: dict[str, Any]

    # IDs of the database records used to build `context`.
    # Provides traceability for which stored records informed the response.
    retrieved_context_ids: list[str]

    # Affect level inferred from the user's audio.
    # Expected values are the system's supported affect levels, such as
    # `Low`, `Moderate`, or `High`.
    affect_level: str

    # Explains why the interaction or a subsystem entered a degraded state.
    # `None` means no degradation reason was recorded.
    degradation_reason: str | None

    # Deadline proximity associated with the current policy evaluation.
    # For non-policy conversational/action turns this may be `n/a`.
    deadline_proximity: str

    # Initial natural-language response drafted by the LLM.
    # This is a draft only; it is not the authoritative record of execution.
    draft_response: str

    # Action suggested by the LLM as metadata about its intended response.
    # This is never authoritative and must not be treated as proof that a
    # mutation actually happened.
    proposed_action: str

    # Result of authoritative action execution.
    # Produced by the executor after validation, reference resolution,
    # and any requested storage mutation.
    # Contains the explicit success/failure outcome of the action.
    execution_outcome: dict[str, Any]

    # Transient reminder-reference resolution status for the execution boundary.
    # Values are internal graph state only; they are not persisted to decision_trace.
    reference_resolution_status: str

    # Marks a turn that is answering a previously issued reminder-reference
    # clarification question. The pending continuation itself lives in the
    # process-local ReferenceClarificationStore, not in this state.
    reference_clarification_active: bool

    # Final user-facing response text after execution outcome, safety checks,
    # and policy processing have been applied.
    final_response: str

    # Policy rule applied to this interaction.
    # For intents outside the reminder-delivery policy domain this is typically `n/a`.
    policy_rule: str

    # Concrete action taken by the policy layer.
    # Describes what the policy decided to do, such as deliver, soften,
    # suppress, or defer when applicable.
    action_taken: str

    # Lead time, in minutes, associated with the reminder policy state.
    # Used by the adaptive reminder lead-time mechanism when applicable.
    lead_time_min: float

    # Outcome recorded for a reminder.
    # Represents the reminder's current outcome state, such as pending,
    # accepted, snoozed, or another defined outcome.
    reminder_outcome: str

    # Structured response returned to the caller/transport layer.
    # Contains the information needed to construct the external response.
    response_payload: dict[str, Any]

    # Trace data assembled by the graph but not yet persisted.
    # InteractionRunner remains the sole writer of the current interaction's trace.
    pending_trace: dict[str, Any]

    # Unique identifier assigned to the current interaction's decision trace.
    # Used to correlate the interaction with its persisted audit record.
    trace_id: str

    # Monotonic host timestamp recorded when the interaction started.
    # Used for reliable elapsed-time measurements without depending on wall-clock changes.
    started_monotonic: float

    # Per-stage elapsed execution times collected during the graph run.
    # The reducer merges timing entries produced by different graph branches.
    stage_timings_s: Annotated[dict[str, float], merge_stage_timings]
