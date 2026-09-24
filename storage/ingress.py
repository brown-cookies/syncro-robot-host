"""External task ingress persistence (SPEC 6.1a)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from storage.database import SQLiteDatabase

# Ingested tasks are not tied to a study participant (SPEC 6.1a), but
# tasks.user_id is NOT NULL with a foreign key, so they are owned by this
# reserved sentinel user instead of any enrolled participant.
INGRESS_USER_ID = "__ingress__"


class IngressRepository:
    """Idempotent task insert keyed on (source, external_id), plus audit log."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def ingest_task(
        self,
        *,
        source: str,
        external_id: str,
        title: str,
        due_at: str | None,
        priority: str,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        """Insert the task unless (source, external_id) was already seen.

        Returns ``(task_row, created)``. The unique partial index
        ``ux_tasks_source_external_id`` is the idempotency guard, so two
        concurrent identical calls cannot both insert. Every call, new or
        duplicate, writes one ``ingress_event_log`` row in the same transaction.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._database.connection() as conn:
            conn.execute(
                "INSERT INTO users(user_id, created_at) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO NOTHING",
                (INGRESS_USER_ID, now),
            )
            task_id = str(uuid4())
            cursor = conn.execute(
                """
                INSERT INTO tasks(
                    task_id, user_id, title, deadline, priority, status,
                    created_at, source, external_id
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (task_id, INGRESS_USER_ID, title, due_at, priority,
                 created_at, source, external_id),
            )
            created = cursor.rowcount == 1
            row = conn.execute(
                "SELECT * FROM tasks WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
            conn.execute(
                "INSERT INTO ingress_event_log("
                "event_id, source, external_id, outcome, task_id, logged_at"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), source, external_id,
                 "created" if created else "duplicate", row["task_id"], now),
            )
            return dict(row), created

    def list_tasks(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Console table read: all tasks, or one user's, oldest first."""
        query = "SELECT * FROM tasks"
        params: tuple[Any, ...] = ()
        if user_id is not None:
            query += " WHERE user_id = ?"
            params = (user_id,)
        query += " ORDER BY created_at, task_id"
        with self._database.connection() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def list_events(self) -> list[dict[str, Any]]:
        """Audit rows for accepted ingest calls, oldest first."""
        with self._database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ingress_event_log ORDER BY logged_at, event_id"
            ).fetchall()
        return [dict(r) for r in rows]
