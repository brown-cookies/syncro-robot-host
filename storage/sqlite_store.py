"""Compatibility facade for the SQLite persistence boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pipeline.contracts import ExecutionOutcome
from storage.context import ContextRepository, ContextResult
from storage.database import SQLiteDatabase
from storage.decision_trace import DecisionTraceRepository
from storage.schema import initialize_schema


class SQLiteStore:
    """Facade preserving the existing WP-103 API while storage responsibilities stay separated."""

    def __init__(self, db_path: str) -> None:
        """Initialize the SQLiteStore and establish its runtime state."""
        self.database = SQLiteDatabase(db_path)
        with self.database.connection() as conn:
            initialize_schema(conn)
        self.context = ContextRepository(self.database)
        self.decision_trace = DecisionTraceRepository(self.database)

    @property
    def path(self) -> str:
        """Return the configured path used by the backing storage."""
        return self.database.path

    def ensure_user(
        self,
        user_id: str,
        *,
        declared_working_window_start: str | None = None,
        declared_working_window_end: str | None = None,
    ) -> None:
        """Create the requested user record when it does not already exist."""
        if not user_id:
            raise ValueError("user_id is required")
        from datetime import datetime, timezone

        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO users(
                    user_id, created_at, declared_working_window_start, declared_working_window_end
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (
                    user_id,
                    datetime.now(timezone.utc).isoformat(),
                    declared_working_window_start,
                    declared_working_window_end,
                ),
            )

    def retrieve_context(self, user_id: str, top_k: int, deadline_proximity_hours: int) -> ContextResult:
        """Retrieve bounded context data for the requested user."""
        return self.context.retrieve(user_id, top_k, deadline_proximity_hours)

    def save_decision_trace(self, record: dict[str, Any]) -> None:
        """Persist a decision trace while preserving the storage contract."""
        self.decision_trace.save(record)

    def save_degraded_trace(self, record: dict[str, Any]) -> None:
        """Persist a validated degraded interaction trace."""
        self.decision_trace.save_degraded(record)

    def suppress_pending_reminder_traces(self, user_id: str) -> int:
        """Suppress other pending reminder traces when policy requires it."""
        return self.decision_trace.suppress_pending_reminder_traces(user_id)

    def get_lead_time(self, user_id: str, default: float) -> float:
        """Read the configured lead-time value used by policy evaluation."""
        with self.database.connection() as conn:
            row = conn.execute(
                "SELECT current_L FROM lead_time_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return float(row["current_L"]) if row is not None else float(default)

    def list_decision_traces(self, user_id: str) -> list[dict[str, Any]]:
        """List stored decision traces for the requested user."""
        return self.decision_trace.list_for_user(user_id)

    # --- Phase 17 Phase 2: task mutations & reminder outcome ---------------
    #
    # Both mutate the existing `tasks`/`decision_trace` tables (no schema
    # change) and are the storage boundary the Phase 3 `ActionExecutor`
    # calls into. Neither invents a fallback target: a caller that can't
    # name a task or a reminder gets `invalid_slots` at the contract layer
    # (pipeline/contracts.py) before it ever reaches here.

    def save_task(
        self,
        user_id: str,
        title: str,
        *,
        deadline: datetime | None = None,
        notes: str | None = None,
        priority: str = "normal",
    ) -> str:
        """Create a new task row and return its generated ``task_id``.

        The id is generated here, at the persistence boundary -- this
        method never accepts a model-generated id (plan Phase 2: "never
        accepts a model-generated id"), so nothing upstream of storage can
        smuggle an LLM-hallucinated id into a real row.
        """
        if not user_id:
            raise ValueError("user_id is required")
        if not title:
            raise ValueError("title is required")

        task_id = str(uuid4())
        now = datetime.now(timezone.utc)
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks(
                    task_id, user_id, title, deadline, notes, priority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    title,
                    deadline.isoformat() if deadline else None,
                    notes,
                    priority,
                    now.isoformat(),
                ),
            )
        return task_id

    def reschedule_task(
        self, user_id: str, task_id: str, new_deadline: datetime
    ) -> bool:
        """Update an existing task's deadline in place.

        User-scoped (the ``WHERE`` clause matches both ``task_id`` and
        ``user_id``, so another user's task is never touched) and verifies
        the task exists: returns ``True`` iff exactly one row was updated,
        ``False`` if no task with that id exists for this user. ``task_id``
        is the table's primary key, so more than one row can never match.
        """
        if not user_id:
            raise ValueError("user_id is required")
        if not task_id:
            raise ValueError("task_id is required")

        with self.database.connection() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET deadline = ? WHERE task_id = ? AND user_id = ?",
                (new_deadline.isoformat(), task_id, user_id),
            )
            updated = cursor.rowcount
        return updated == 1

    # Alias matching the plan's "reschedule_task(...) / update_task_deadline(...)"
    # naming -- one method, two names in the plan text; this is the same
    # callable under both.
    update_task_deadline = reschedule_task

    def update_reminder_outcome(
        self,
        *,
        user_id: str,
        trace_id: str,
        outcome: Literal["accepted", "snoozed"],
        snooze_minutes: int | None = None,
        response_window_minutes: int,
        adaptive_lead_time_enabled: bool,
        alpha: float,
        lead_time_min: float,
        lead_time_max: float,
        default_lead_time: float,
    ) -> ExecutionOutcome:
        """Resolve one pending reminder and update the adaptive lead-time
        parameter, atomically. See
        ``DecisionTraceRepository.update_reminder_outcome`` for the full
        contract; every tunable here is threaded through from
        ``config.settings.Settings`` by the caller (Phase 3's
        ``ActionExecutor``) rather than hardcoded in this facade.
        """
        return self.decision_trace.update_reminder_outcome(
            user_id=user_id,
            trace_id=trace_id,
            outcome=outcome,
            snooze_minutes=snooze_minutes,
            response_window_minutes=response_window_minutes,
            adaptive_lead_time_enabled=adaptive_lead_time_enabled,
            alpha=alpha,
            lead_time_min=lead_time_min,
            lead_time_max=lead_time_max,
            default_lead_time=default_lead_time,
        )
