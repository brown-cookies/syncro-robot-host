"""Seed a deterministic WP-103 SQLite dataset for local testing."""

from __future__ import annotations

import argparse
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from config.settings import get_settings
from storage.sqlite_store import SQLiteStore

USER_ID = "wp103-demo-user"


def _task(task_id: str, title: str, deadline: datetime | None, priority: str, now: datetime) -> tuple:
    return (
        task_id,
        USER_ID,
        title,
        deadline.isoformat() if deadline else None,
        f"Sample WP-103 task: {title}",
        priority,
        "overdue" if deadline is not None and deadline < now else "pending",
        now.isoformat(),
        None,
        str(uuid.uuid4()),
        "wp103-seed",
        task_id,
    )


def seed(db_path: str, reset: bool = True) -> None:
    SQLiteStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        now = datetime.now(timezone.utc)
        if reset:
            conn.execute("DELETE FROM decision_trace WHERE user_id = ?", (USER_ID,))
            conn.execute("DELETE FROM routine_log WHERE user_id = ?", (USER_ID,))
            conn.execute("DELETE FROM tasks WHERE user_id = ?", (USER_ID,))
            conn.execute("DELETE FROM lead_time_state WHERE user_id = ?", (USER_ID,))
            conn.execute("DELETE FROM users WHERE user_id = ?", (USER_ID,))

        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, created_at, declared_working_window_start, declared_working_window_end) "
            "VALUES (?, ?, ?, ?)",
            (USER_ID, now.isoformat(), "08:00", "22:00"),
        )

        tasks = [
            _task("wp103-task-overdue", "Submit thesis outline", now - timedelta(hours=2), "high", now),
            _task("wp103-task-imminent-high", "Prepare presentation slides", now + timedelta(minutes=45), "high", now),
            _task("wp103-task-imminent-normal", "Review methodology notes", now + timedelta(minutes=90), "normal", now),
            _task("wp103-task-far-high", "Organize reference papers", now + timedelta(hours=5), "high", now),
            _task("wp103-task-far-normal", "Read related literature", now + timedelta(hours=8), "normal", now),
            _task("wp103-task-no-deadline", "Clean project repository", None, "low", now),
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO tasks(
                task_id,user_id,title,deadline,notes,priority,status,created_at,
                completed_at,client_write_id,source,external_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            tasks,
        )

        conn.execute(
            "INSERT OR REPLACE INTO routine_log(log_id,user_id,event_type,logged_at) VALUES (?,?,?,?)",
            ("wp103-routine-1", USER_ID, "routine", (now - timedelta(minutes=20)).isoformat()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO routine_log(log_id,user_id,event_type,logged_at) VALUES (?,?,?,?)",
            ("wp103-break-1", USER_ID, "break", (now - timedelta(minutes=5)).isoformat()),
        )
        conn.execute(
            """INSERT INTO lead_time_state(user_id,current_L,last_updated_at)
               VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   current_L=excluded.current_L,
                   last_updated_at=excluded.last_updated_at""",
            (USER_ID, 15.0, now.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite path; defaults to config.db_path")
    parser.add_argument("--no-reset", action="store_true", help="Keep existing WP-103 demo rows")
    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db or settings.db_path
    seed(db_path, reset=not args.no_reset)

    print(f"WP-103 SQLite seed ready: {db_path}")
    print(f"Demo user: {USER_ID}")
    print("Seeded tasks relative to the current UTC time: overdue, 45m/high, 90m/normal, 5h/high, 8h/normal, no-deadline/low")
    print("Seeded routine log: routine + break")
    print("Seeded lead_time_state: L=15.0 minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
