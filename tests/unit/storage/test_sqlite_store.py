import pytest
from datetime import datetime, timedelta, timezone
import sqlite3

from storage.context import ContextRepository
from storage.database import SQLiteDatabase
from storage.decision_trace import DecisionTraceRepository
from storage.schema import initialize_schema
from storage.sqlite_store import SQLiteStore


def test_context_returns_tasks_routine_and_overdue(tmp_path):
    """Verify that context returns tasks routine and overdue."""
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
    assert result.deadline_proximity == "not_imminent"
    assert "t1" in result.ids


def test_sqlite_schema_matches_spec_section_9(tmp_path):
    """Verify that sqlite schema matches spec section 9."""
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
    """Verify that seed marks past deadline task overdue."""
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
    """Verify that storage responsibilities are separated."""
    db = SQLiteDatabase(str(tmp_path / "separation.db"))
    with db.connect() as conn:
        initialize_schema(conn)
    context = ContextRepository(db)
    traces = DecisionTraceRepository(db)
    assert context is not None
    assert traces is not None
    assert db.path.endswith("separation.db")


def test_context_is_scoped_to_requesting_user(tmp_path):
    """Verify that context is scoped to requesting user."""
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
    """Verify that r5 suppresses other pending reminder traces."""
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


def test_overdue_task_does_not_count_as_imminent(tmp_path):
    """Verify that overdue task does not count as imminent."""
    store = SQLiteStore(str(tmp_path / "deadline.db"))
    now = datetime.now(timezone.utc)
    with sqlite3.connect(str(tmp_path / "deadline.db")) as conn:
        conn.execute("INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
        conn.execute(
            """INSERT INTO tasks(task_id,user_id,title,deadline,priority,status,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            ("stale", "u1", "Stale", (now - timedelta(days=90)).isoformat(), "normal", "overdue", now.isoformat()),
        )
    result = store.retrieve_context("u1", 5, 2)
    assert result.overdue_tasks[0]["task_id"] == "stale"
    assert result.deadline_proximity == "not_imminent"


def test_overdue_context_is_bounded(tmp_path):
    """Verify that overdue context is bounded."""
    store = SQLiteStore(str(tmp_path / "bounded.db"))
    now = datetime.now(timezone.utc)
    with sqlite3.connect(str(tmp_path / "bounded.db")) as conn:
        conn.execute("INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
        for i in range(20):
            deadline = (now - timedelta(days=i + 1)).isoformat()
            conn.execute(
                """INSERT INTO tasks(task_id,user_id,title,deadline,priority,status,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (f"stale-{i}", "u1", f"Stale {i}", deadline, "normal", "overdue", now.isoformat()),
            )
    result = store.retrieve_context("u1", 5, 2)
    assert len(result.overdue_tasks) == 5


def test_database_connection_context_closes_connection(tmp_path):
    """Verify that database connection context closes connection."""
    db = SQLiteDatabase(str(tmp_path / "close.db"))
    with db.connection() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_ensure_user_is_idempotent(tmp_path):
    """Verify that ensure user is idempotent."""
    store = SQLiteStore(str(tmp_path / "user.db"))
    store.ensure_user("demo", declared_working_window_start="08:00", declared_working_window_end="22:00")
    store.ensure_user("demo", declared_working_window_start="09:00", declared_working_window_end="21:00")
    with sqlite3.connect(str(tmp_path / "user.db")) as conn:
        row = conn.execute(
            "SELECT user_id, declared_working_window_start, declared_working_window_end FROM users WHERE user_id = ?",
            ("demo",),
        ).fetchone()
    assert row == ("demo", "08:00", "22:00")


def test_output_node_returns_pending_trace_without_persisting_it(tmp_path):
    from pipeline.nodes.output import make_output_node

    store = SQLiteStore(str(tmp_path / "pending.db"))
    output_node = make_output_node()

    result = output_node(
        {
            "session_id": "s1",
            "user_id": "new-user",
            "final_response": "You have one priority task.",
            "intent": "ask_status",
            "intent_confidence": 0.9,
            "affect_level": "Low",
        }
    )

    assert result["response_payload"]["tts_text"] == "You have one priority task."
    pending = result["pending_trace"]
    assert pending["session_id"] == "s1"
    assert pending["user_id"] == "new-user"
    assert "latency_ms" not in pending
    assert "latency_basis" not in pending
    assert store.list_decision_traces("new-user") == []


def test_output_node_does_not_require_store_for_trace_assembly():
    from pipeline.nodes.output import make_output_node

    output_node = make_output_node()
    result = output_node(
        {
            "session_id": "s2",
            "user_id": "u2",
            "final_response": "Done.",
            "intent": "ask_status",
            "intent_confidence": 1.0,
            "affect_level": "Moderate",
        }
    )

    assert result["pending_trace"]["trace_id"]




def test_degraded_trace_round_trips_with_null_interaction_fields(tmp_path):
    from uuid import uuid4

    store = SQLiteStore(str(tmp_path / "degraded.db"))
    store.ensure_user("u-degraded")
    store.save_degraded_trace({
        "trace_id": uuid4(),
        "session_id": "s-degraded",
        "user_id": "u-degraded",
        "timestamp": datetime.now(timezone.utc),
        "degradation_reason": "pipeline_failure",
        "network_event": None,
        "latency_ms": 0.0,
        "latency_basis": "host_observed_only",
    })

    row = store.list_decision_traces("u-degraded")[0]
    assert row["intent"] is None
    assert row["intent_confidence"] is None
    assert row["retrieved_context_ids"] is None
    assert row["affect_level"] is None
    assert row["policy_rule"] == "n/a"
    assert row["degradation_reason"] == "pipeline_failure"


def test_degraded_trace_can_be_standalone_without_session_id(tmp_path):
    from uuid import uuid4

    store = SQLiteStore(str(tmp_path / "standalone.db"))
    store.ensure_user("u-standalone")
    store.save_degraded_trace({
        "trace_id": uuid4(),
        "session_id": None,
        "user_id": "u-standalone",
        "timestamp": datetime.now(timezone.utc),
        "degradation_reason": "queue_overflow",
    })

    row = store.list_decision_traces("u-standalone")[0]
    assert row["session_id"] is None
    assert row["degradation_reason"] == "queue_overflow"
    assert row["policy_rule"] == "n/a"


def test_decision_trace_repository_still_rejects_invalid_normal_rows(tmp_path):
    from uuid import uuid4

    store = SQLiteStore(str(tmp_path / "strict.db"))
    store.ensure_user("u-strict")
    with pytest.raises(ValueError):
        store.save_decision_trace({
            "trace_id": uuid4(),
            "session_id": "s1",
            "user_id": "u-strict",
            "timestamp": datetime.now(timezone.utc),
            "intent": None,
            "intent_confidence": None,
            "retrieved_context_ids": [],
            "affect_level": None,
            "deadline_proximity": "n/a",
            "policy_rule": "n/a",
            "action_taken": "deliver",
            "lead_time_min": 15.0,
            "reminder_outcome": "n/a",
            "degradation_reason": None,
            "network_event": None,
            "latency_ms": 1.0,
            "latency_basis": "host_observed_only",
        })
