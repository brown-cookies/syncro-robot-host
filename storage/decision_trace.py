"""Decision-trace persistence for WP-103."""

from __future__ import annotations

import json
from typing import Any

from pipeline.contracts import DecisionTraceRecord
from storage.database import SQLiteDatabase


TRACE_FIELDS = (
    "trace_id", "session_id", "user_id", "timestamp", "intent",
    "intent_confidence", "retrieved_context_ids", "affect_level",
    "deadline_proximity", "policy_rule", "action_taken", "lead_time_min",
    "reminder_outcome", "degradation_reason", "network_event", "latency_ms",
    "latency_basis",
)


class DecisionTraceRepository:
    """Validates and persists complete Section 8.3 trace records."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, record: dict[str, Any]) -> None:
        validated = DecisionTraceRecord.model_validate(record)
        record_json = validated.model_dump(mode="json")
        values = [record_json[name] for name in TRACE_FIELDS]
        values[6] = json.dumps(values[6])

        with self._database.connection() as conn:
            conn.execute(
                f"INSERT INTO decision_trace ({', '.join(TRACE_FIELDS)}) "
                f"VALUES ({', '.join('?' for _ in TRACE_FIELDS)})",
                values,
            )

    def suppress_pending_reminder_traces(self, user_id: str) -> int:
        """Mark other pending reminder trace rows as suppressed for R5."""
        if not user_id:
            raise ValueError("user_id is required")
        with self._database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE decision_trace
                   SET action_taken = 'suppress'
                 WHERE user_id = ?
                   AND reminder_outcome = 'pending'
                   AND action_taken <> 'suppress'
                """,
                (user_id,),
            )
            return cursor.rowcount

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM decision_trace WHERE user_id = ? ORDER BY timestamp ASC",
                (user_id,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["retrieved_context_ids"] = json.loads(item["retrieved_context_ids"])
            result.append(item)
        return result
