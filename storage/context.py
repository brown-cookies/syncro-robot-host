"""Participant context retrieval for WP-103 Node 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from storage.database import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class ContextResult:
    tasks: list[dict[str, Any]]
    recent_routine: dict[str, Any] | None
    overdue_tasks: list[dict[str, Any]]
    deadline_proximity: str

    @property
    def ids(self) -> list[str]:
        ids = [str(item["task_id"]) for item in self.tasks]
        ids.extend(
            str(item["task_id"])
            for item in self.overdue_tasks
            if str(item["task_id"]) not in ids
        )
        if self.recent_routine is not None:
            ids.append(str(self.recent_routine["log_id"]))
        return ids


class ContextRepository:
    """Queries the context required by SPEC FR-H5."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def retrieve(
        self,
        user_id: str,
        top_k: int,
        deadline_proximity_hours: int,
    ) -> ContextResult:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        overdue_limit = max(top_k, 1)

        with self._database.connection() as conn:
            upcoming_rows = conn.execute(
                """
                SELECT task_id, title, deadline, priority, status, notes, created_at
                FROM tasks
                WHERE user_id = ?
                  AND status != 'completed'
                  AND (deadline IS NULL OR deadline >= ?)
                ORDER BY
                    CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
                    deadline ASC,
                    created_at ASC
                LIMIT ?
                """,
                (user_id, now_iso, top_k),
            ).fetchall()

            recent_routine = conn.execute(
                """
                SELECT log_id, event_type, logged_at
                FROM routine_log
                WHERE user_id = ?
                ORDER BY logged_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

            overdue_rows = conn.execute(
                """
                SELECT task_id, title, deadline, priority, status, notes, created_at
                FROM tasks
                WHERE user_id = ?
                  AND status != 'completed'
                  AND deadline IS NOT NULL
                ORDER BY deadline ASC, created_at ASC
                LIMIT ?
                """,
                (user_id, overdue_limit),
            ).fetchall()

        tasks = [dict(row) for row in upcoming_rows]
        overdue: list[dict[str, Any]] = []
        for row in overdue_rows:
            task = dict(row)
            try:
                deadline = datetime.fromisoformat(
                    str(task["deadline"]).replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if task["status"] == "overdue" or deadline < now:
                overdue.append(task)

        imminent = False
        for task in [*tasks, *overdue]:
            deadline_value = task.get("deadline")
            if not deadline_value:
                continue
            try:
                deadline = datetime.fromisoformat(
                    str(deadline_value).replace("Z", "+00:00")
                )
            except ValueError:
                continue
            delta_hours = (deadline - now).total_seconds() / 3600.0
            if 0 <= delta_hours <= deadline_proximity_hours:
                imminent = True
                break

        return ContextResult(
            tasks=tasks,
            recent_routine=dict(recent_routine) if recent_routine else None,
            overdue_tasks=overdue,
            deadline_proximity="imminent" if imminent else "not_imminent",
        )
