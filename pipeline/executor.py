"""Phase 17/3 action executor: authoritative task and reminder mutations."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from pipeline.contracts import (
    AddTaskSlots,
    DismissReminderSlots,
    ExecutionOutcome,
    RescheduleTaskSlots,
    SnoozeReminderSlots,
)
from pipeline.state import DialogueState

EXECUTABLE_INTENTS = frozenset({
    "add_task",
    "reschedule_task",
    "snooze_reminder",
    "dismiss_reminder",
})


class ActionExecutor:
    """Own authoritative mutation for the four executable intents.

    The executor consumes the context already produced by Node 2. It never
    re-fetches context after a mutation, never asks the LLM for a target, never
    applies reminder policy, and never writes the current turn's decision trace.
    """

    def __init__(
        self,
        store,
        *,
        reminder_response_window_minutes: int,
        adaptive_lead_time_enabled: bool,
        alpha: float,
        lead_time_min: float,
        lead_time_max: float,
        default_lead_time: float,
    ) -> None:
        """Initialize the executor with the shared storage boundary and settings."""
        self._store = store
        self._reminder_response_window_minutes = reminder_response_window_minutes
        self._adaptive_lead_time_enabled = adaptive_lead_time_enabled
        self._alpha = alpha
        self._lead_time_min = lead_time_min
        self._lead_time_max = lead_time_max
        self._default_lead_time = default_lead_time

    @property
    def store(self):
        """Return the exact shared SQLiteStore instance used by the host."""
        return self._store

    def execute(self, state: DialogueState) -> ExecutionOutcome:
        """Validate, resolve, and execute one supported action intent."""
        intent = state.get("intent")
        user_id = state.get("user_id")
        if not isinstance(intent, str) or intent not in EXECUTABLE_INTENTS:
            raise ValueError(
                f"ActionExecutor received non-executable intent: {intent!r}"
            )
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("ActionExecutor requires user_id in DialogueState")

        slots = state.get("slots", {})
        if not isinstance(slots, dict):
            return self._failure(intent, "invalid_slots", "slots must be an object")

        if intent == "add_task":
            return self._execute_add_task(user_id, slots)
        if intent == "reschedule_task":
            return self._execute_reschedule_task(user_id, slots, state)
        if intent == "snooze_reminder":
            return self._execute_reminder(user_id, slots, "snoozed")
        return self._execute_reminder(user_id, slots, "accepted")

    def _execute_add_task(
        self, user_id: str, raw_slots: dict[str, Any]
    ) -> ExecutionOutcome:
        try:
            slots = AddTaskSlots.model_validate(raw_slots)
        except ValidationError as exc:
            return self._failure(
                "add_task", "invalid_slots", _validation_detail(exc)
            )

        task_id = self._store.save_task(
            user_id,
            slots.title,
            deadline=slots.deadline,
            notes=slots.notes,
            priority=slots.priority,
        )
        return ExecutionOutcome(
            succeeded=True,
            intent="add_task",
            target_id=task_id,
            detail=f"task {task_id!r} created",
        )

    def _execute_reschedule_task(
        self,
        user_id: str,
        raw_slots: dict[str, Any],
        state: DialogueState,
    ) -> ExecutionOutcome:
        raw_reference = raw_slots.get("task_reference")
        raw_task_id = raw_slots.get("task_id")

        if isinstance(raw_task_id, str) and raw_task_id.strip() and raw_reference is None:
            task_id = raw_task_id.strip()
        else:
            if not isinstance(raw_reference, str) or not raw_reference.strip():
                return self._failure(
                    "reschedule_task",
                    "invalid_slots",
                    "reschedule_task requires an explicit task_reference",
                )
            task_id = self._resolve_task_reference(
                raw_reference,
                state.get("context", {}),
            )
            if task_id is None:
                matches = self._matching_task_ids(raw_reference, state.get("context", {}))
                if not matches:
                    return self._failure(
                        "reschedule_task",
                        "task_not_found",
                        f"no task matches reference {raw_reference!r}",
                    )
                return self._failure(
                    "reschedule_task",
                    "ambiguous_task",
                    f"task reference {raw_reference!r} matches more than one task",
                )

        try:
            slots = RescheduleTaskSlots(
                task_id=task_id,
                new_deadline=raw_slots.get("new_deadline"),
            )
        except ValidationError as exc:
            return self._failure(
                "reschedule_task", "invalid_slots", _validation_detail(exc)
            )

        updated = self._store.reschedule_task(
            user_id, slots.task_id, slots.new_deadline
        )
        if not updated:
            return self._failure(
                "reschedule_task",
                "task_not_found",
                f"task {slots.task_id!r} was not found for this user",
            )

        return ExecutionOutcome(
            succeeded=True,
            intent="reschedule_task",
            target_id=slots.task_id,
            detail=f"task {slots.task_id!r} rescheduled",
        )

    def _execute_reminder(
        self,
        user_id: str,
        raw_slots: dict[str, Any],
        outcome: str,
    ) -> ExecutionOutcome:
        model_type = SnoozeReminderSlots if outcome == "snoozed" else DismissReminderSlots
        try:
            slots = model_type.model_validate(raw_slots)
        except ValidationError as exc:
            intent = "snooze_reminder" if outcome == "snoozed" else "dismiss_reminder"
            return self._failure(intent, "invalid_slots", _validation_detail(exc))

        intent = "snooze_reminder" if outcome == "snoozed" else "dismiss_reminder"
        snooze_minutes = slots.snooze_minutes if outcome == "snoozed" else None
        return self._store.update_reminder_outcome(
            user_id=user_id,
            trace_id=slots.reference_trace_id,
            outcome=outcome,
            snooze_minutes=snooze_minutes,
            response_window_minutes=self._reminder_response_window_minutes,
            adaptive_lead_time_enabled=self._adaptive_lead_time_enabled,
            alpha=self._alpha,
            lead_time_min=self._lead_time_min,
            lead_time_max=self._lead_time_max,
            default_lead_time=self._default_lead_time,
        )

    @staticmethod
    def _matching_task_ids(reference: str, context: dict[str, Any]) -> list[str]:
        """Return task IDs whose titles exactly match the user reference."""
        normalized_reference = _normalize_reference(reference)
        if not normalized_reference or not isinstance(context, dict):
            return []

        seen: set[str] = set()
        matches: list[str] = []
        for collection_name in ("tasks", "overdue_tasks"):
            collection = context.get(collection_name, [])
            if not isinstance(collection, list):
                continue
            for task in collection:
                if not isinstance(task, dict):
                    continue
                task_id = task.get("task_id")
                title = task.get("title")
                if not isinstance(task_id, str) or not task_id:
                    continue
                if task_id in seen:
                    continue
                seen.add(task_id)
                if isinstance(title, str) and _normalize_reference(title) == normalized_reference:
                    matches.append(task_id)
        return matches

    def _resolve_task_reference(
        self, reference: str, context: dict[str, Any]
    ) -> str | None:
        """Resolve an exact task-title reference against Node 2's context."""
        matches = self._matching_task_ids(reference, context)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _failure(intent: str, error_code: str, detail: str) -> ExecutionOutcome:
        return ExecutionOutcome(
            succeeded=False,
            intent=intent,
            error_code=error_code,
            detail=detail,
        )


def _normalize_reference(value: str) -> str:
    """Normalize explicit task references without introducing fuzzy matching."""
    return " ".join(value.casefold().split())


def _validation_detail(exc: ValidationError) -> str:
    """Reduce Pydantic validation output to a stable human-readable detail."""
    errors = exc.errors()
    if not errors:
        return "action slots failed validation"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "slots"
    message = str(first.get("msg", "invalid value"))
    return f"invalid {location}: {message}"
