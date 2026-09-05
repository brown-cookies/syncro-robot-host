"""Compatibility facade for the SQLite persistence boundary."""

from __future__ import annotations

from typing import Any

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
