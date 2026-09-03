from datetime import datetime, timedelta, timezone
import sqlite3

from storage.context import ContextRepository
from storage.database import SQLiteDatabase
from storage.decision_trace import DecisionTraceRepository
from storage.schema import initialize_schema
from storage.sqlite_store import SQLiteStore


def test_context_returns_tasks_routine_and_overdue(tmp_path):
    store = SQLiteStore(str(tmp_path / "test.db"))
    now = datetime.now(timezone.utc)
    with sqlite3.connect(str(tmp_path / "test.db")) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
        conn.execute(
            """INSERT INTO tasks(
                task_id, user_id, title, deadline, priority, status, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "t1", "u1", "Overdue", (now-timedelta(hours=1)).isoformat(),
                "high", "overdue", "", now.isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO routine_log(log_id, user_id, event_type, logged_at) VALUES (?, ?, ?, ?)",
            ("r1", "u1", "break", now.isoformat()),
        )
    result = store.retrieve_context("u1", 5, 2)
    assert result.recent_routine["log_id"] == "r1"
    assert result.overdue_tasks[0]["task_id"] == "t1"
    assert result.deadline_proximity == "imminent"
    assert "t1" in result.ids


def test_sqlite_schema_matches_spec_section_9(tmp_path):
    db_path = tmp_path / "schema.db"
    SQLiteStore(str(db_path))
    expected = {
        "users": {"user_id", "created_at", "declared_working_window_start", "declared_working_window_end"},
        "tasks": {"task_id", "user_id", "title", "deadline", "notes", "priority", "status", "created_at", "completed_at", "client_write_id", "source", "external_id"},
        "routine_log": {"log_id", "user_id", "event_type", "logged_at"},
        "decision_trace": {"trace_id", "session_id", "user_id", "timestamp", "intent", "intent_confidence", "retrieved_context_ids", "affect_level", "deadline_proximity", "policy_rule", "action_taken", "lead_time_min", "reminder_outcome", "degradation_reason", "network_event", "latency_ms", "latency_basis"},
        "lead_time_state": {"user_id", "current_L", "last_updated_at"},
        "activity_buckets": {"bucket_id", "user_id", "minute_start", "active_seconds", "idle_seconds"},
        "consent_records": {"record_id", "user_id", "submitted_at", "payload", "client_write_id"},
        "self_reports": {"record_id", "user_id", "submitted_at", "payload", "client_write_id"},
        "exit_survey_responses": {"record_id", "user_id", "submitted_at", "payload", "client_write_id"},
        "outages": {"outage_id", "user_id", "started_at", "ended_at", "affected_interaction_count"},
        "deletion_receipts": {"user_id", "requested_at", "client_write_id", "tables_cleared"},
    }
    with sqlite3.connect(str(db_path)) as conn:
        for table, columns in expected.items():
            actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert actual == columns, table


def test_seed_marks_past_deadline_task_overdue(tmp_path):
    from scripts.seed_wp103 import seed

    db_path = tmp_path / "seed.db"
    seed(str(db_path), reset=True)
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT status, priority FROM tasks WHERE task_id = ?",
            ("wp103-task-overdue",),
        ).fetchone()
    assert row == ("overdue", "high")


def test_storage_responsibilities_are_separated(tmp_path):
    db = SQLiteDatabase(str(tmp_path / "separation.db"))
    with db.connect() as conn:
        initialize_schema(conn)
    context = ContextRepository(db)
    traces = DecisionTraceRepository(db)
    assert context is not None
    assert traces is not None
    assert db.path.endswith("separation.db")


def test_context_is_scoped_to_requesting_user(tmp_path):
    store = SQLiteStore(str(tmp_path / "scope.db"))
    now = datetime.now(timezone.utc)
    with sqlite3.connect(str(tmp_path / "scope.db")) as conn:
        conn.execute("INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
        conn.execute("INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u2", now.isoformat()))
        for user_id, task_id in (("u1", "u1-task"), ("u2", "u2-task")):
            conn.execute(
                """INSERT INTO tasks(task_id,user_id,title,deadline,priority,status,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (task_id, user_id, task_id, (now + timedelta(hours=1)).isoformat(), "normal", "pending", now.isoformat()),
            )
    result = store.retrieve_context("u1", 5, 2)
    assert [row["task_id"] for row in result.tasks] == ["u1-task"]
    assert "u2-task" not in result.ids


def test_r5_suppresses_other_pending_reminder_traces(tmp_path):
    from uuid import uuid4
    from pipeline.nodes.output import make_output_node

    store = SQLiteStore(str(tmp_path / "trace.db"))
    now = datetime.now(timezone.utc)
    with sqlite3.connect(str(tmp_path / "trace.db")) as conn:
        conn.execute("INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))

    base = {
        "trace_id": str(uuid4()),
        "session_id": "old",
        "user_id": "u1",
        "timestamp": now.isoformat(),
        "intent": "dismiss_reminder",
        "intent_confidence": 0.9,
        "retrieved_context_ids": [],
        "affect_level": "High",
        "deadline_proximity": "imminent",
        "policy_rule": "R5",
        "action_taken": "deliver",
        "lead_time_min": 15.0,
        "reminder_outcome": "pending",
        "degradation_reason": None,
        "network_event": None,
        "latency_ms": 1.0,
        "latency_basis": "host_observed_only",
    }
    store.save_decision_trace(base)
    assert store.suppress_pending_reminder_traces("u1") == 1
    row = store.list_decision_traces("u1")[0]
    assert row["action_taken"] == "suppress"
