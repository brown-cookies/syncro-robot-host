"""Phase 17 reminder-reference resolution before authoritative execution."""

from __future__ import annotations

from typing import Any

from pipeline.reference_resolution import (
    AMBIGUOUS,
    PendingReferenceClarification,
    ReferenceCandidate,
    ReferenceClarificationStore,
    build_clarification_prompt,
    resolve_clarification_answer,
)
from pipeline.state import DialogueState


REMINDER_INTENTS = frozenset({"snooze_reminder", "dismiss_reminder"})


def make_reference_resolution_node(
    store,
    clarification_store: ReferenceClarificationStore,
    *,
    reminder_response_window_minutes: int,
):
    """Create the pre-execution reminder-reference resolver."""

    def reference_resolution_node(state: DialogueState) -> DialogueState:
        intent = state.get("intent")
        if intent not in REMINDER_INTENTS:
            return {}
        if state.get("proposed_action") == "clarify":
            return {}

        user_id = state.get("user_id")
        transcript = state.get("transcript")
        raw_slots = state.get("slots", {})
        if not isinstance(user_id, str) or not user_id:
            raise RuntimeError("Reference resolution requires user_id")
        if not isinstance(transcript, str):
            raise RuntimeError("Reference resolution requires transcript")
        if not isinstance(raw_slots, dict):
            return {"reference_resolution_status": "not_found"}

        explicit_trace_id = raw_slots.get("reference_trace_id")
        if isinstance(explicit_trace_id, str) and explicit_trace_id.strip():
            return {
                "slots": {**raw_slots, "reference_trace_id": explicit_trace_id.strip()},
                "reference_resolution_status": "resolved",
                "reference_clarification_active": False,
            }

        pending = clarification_store.get(user_id)
        if pending is not None:
            candidates = _active_candidates(
                store,
                user_id,
                reminder_response_window_minutes,
                pending.candidates,
            )
            if not candidates:
                clarification_store.clear(user_id)
                return {"reference_resolution_status": "not_found"}

            resolution = resolve_clarification_answer(transcript, candidates)
            if isinstance(resolution, ReferenceCandidate):
                clarification_store.clear(user_id)
                return {
                    "slots": {
                        **pending.slots,
                        "reference_trace_id": resolution.trace_id,
                    },
                    "reference_resolution_status": "resolved",
                    "reference_clarification_active": False,
                }

            prompt = build_clarification_prompt(candidates)
            return {
                "final_response": prompt,
                "proposed_action": "clarify",
                "reference_resolution_status": "needs_clarification",
                "reference_clarification_active": True,
            }

        candidate_rows = store.list_pending_reminder_references(
            user_id,
            response_window_minutes=reminder_response_window_minutes,
            limit=10,
        )
        candidates = tuple(
            ReferenceCandidate(
                trace_id=item.trace_id,
                label=item.label,
                title=item.title,
            )
            for item in candidate_rows
        )

        if not candidates:
            return {
                "reference_resolution_status": "not_found",
                "reference_clarification_active": False,
            }

        resolution = resolve_clarification_answer(transcript, candidates)
        if isinstance(resolution, ReferenceCandidate):
            return {
                "slots": {
                    **raw_slots,
                    "reference_trace_id": resolution.trace_id,
                },
                "reference_resolution_status": "resolved",
                "reference_clarification_active": False,
            }

        if len(candidates) == 1 and resolution is None:
            # A single active pending reminder is not a "most recent" heuristic:
            # there is exactly one valid candidate to choose from for this user.
            return {
                "slots": {
                    **raw_slots,
                    "reference_trace_id": candidates[0].trace_id,
                },
                "reference_resolution_status": "resolved",
                "reference_clarification_active": False,
            }

        clarification_store.put(
            PendingReferenceClarification(
                user_id=user_id,
                intent=intent,
                intent_confidence=float(state.get("intent_confidence", 0.0)),
                slots=dict(raw_slots),
                candidates=candidates,
            )
        )
        return {
            "final_response": build_clarification_prompt(candidates),
            "proposed_action": "clarify",
            "reference_resolution_status": "needs_clarification",
            "reference_clarification_active": True,
        }

    return reference_resolution_node


def _active_candidates(
    store,
    user_id: str,
    response_window_minutes: int,
    previous: tuple[ReferenceCandidate, ...],
) -> tuple[ReferenceCandidate, ...]:
    active_rows = store.list_pending_reminder_references(
        user_id,
        response_window_minutes=response_window_minutes,
        limit=10,
    )
    active_by_id = {
        row.trace_id: ReferenceCandidate(
            trace_id=row.trace_id,
            label=row.label,
            title=row.title,
        )
        for row in active_rows
    }
    return tuple(active_by_id[item.trace_id] for item in previous if item.trace_id in active_by_id)
