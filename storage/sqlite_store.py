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
        self.database = SQLiteDatabase(db_path)
        with self.database.connect() as conn:
            initialize_schema(conn)
        self.context = ContextRepository(self.database)
        self.decision_trace = DecisionTraceRepository(self.database)

    @property
    def path(self) -> str:
        return self.database.path

    def retrieve_context(self, user_id: str, top_k: int, deadline_proximity_hours: int) -> ContextResult:
        return self.context.retrieve(user_id, top_k, deadline_proximity_hours)

    def save_decision_trace(self, record: dict[str, Any]) -> None:
        self.decision_trace.save(record)

    def suppress_pending_reminder_traces(self, user_id: str) -> int:
        return self.decision_trace.suppress_pending_reminder_traces(user_id)

    def get_lead_time(self, user_id: str, default: float) -> float:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT current_L FROM lead_time_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return float(row["current_L"]) if row is not None else float(default)

    def list_decision_traces(self, user_id: str) -> list[dict[str, Any]]:
        return self.decision_trace.list_for_user(user_id)
