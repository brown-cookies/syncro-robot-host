"""Typed state carried through the WP-103 dialogue graph."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_stage_timings(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    """Combine per-stage timing dicts written by parallel graph branches.

    LangGraph calls this reducer with the state's current value as ``left`` and each
    node's returned partial update as ``right`` within the same superstep, so this must
    be commutative and must not mutate either argument.
    """
    return {**left, **right}


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
    degradation_reason: str | None
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

    # Reducer-backed keys: safe for more than one node to write in the same
    # superstep (e.g. the START -> node1_stt / START -> affect fan-out). Every
    # other key above remains last-write-wins and single-writer by convention
    # (see techdocs/ARCH.md ownership notes) - do not add a second writer to a
    # plain key without giving it a reducer here first (see finding F5).
    stage_timings_s: Annotated[dict[str, float], merge_stage_timings]
    degradations: Annotated[list[str], operator.add]
