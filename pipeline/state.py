"""Typed state carried through the WP-103 dialogue graph."""

from __future__ import annotations

from typing import Any, TypedDict


class DialogueState(TypedDict, total=False):
    session_id: str
    user_id: str
    audio: Any
    sample_rate: int
    wake_word_detected_at: int
    transcript: str
    intent: str
    intent_confidence: float
    slots: dict[str, Any]
    context: dict[str, Any]
    retrieved_context_ids: list[str]
    affect_level: str
    deadline_proximity: str
    draft_response: str
    proposed_action: str
    final_response: str
    policy_rule: str
    action_taken: str
    lead_time_min: float
    reminder_outcome: str
    response_payload: dict[str, Any]
    trace_id: str
    started_monotonic: float
