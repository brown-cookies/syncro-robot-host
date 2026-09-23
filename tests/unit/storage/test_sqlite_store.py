from storage.decision_trace import compute_lead_time_ema
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
        conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
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
            actual = {row[1]
                      for row in conn.execute(f"PRAGMA table_info({table})")}
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
        conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
        conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u2", now.isoformat()))
        for user_id, task_id in (("u1", "u1-task"), ("u2", "u2-task")):
            conn.execute(
                """INSERT INTO tasks(task_id,user_id,title,deadline,priority,status,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (task_id, user_id, task_id, (now + timedelta(hours=1)
                                             ).isoformat(), "normal", "pending", now.isoformat()),
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
        conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))

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
        conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
        conn.execute(
            """INSERT INTO tasks(task_id,user_id,title,deadline,priority,status,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            ("stale", "u1", "Stale", (now - timedelta(days=90)
                                      ).isoformat(), "normal", "overdue", now.isoformat()),
        )
    result = store.retrieve_context("u1", 5, 2)
    assert result.overdue_tasks[0]["task_id"] == "stale"
    assert result.deadline_proximity == "not_imminent"


def test_overdue_context_is_bounded(tmp_path):
    """Verify that overdue context is bounded."""
    store = SQLiteStore(str(tmp_path / "bounded.db"))
    now = datetime.now(timezone.utc)
    with sqlite3.connect(str(tmp_path / "bounded.db")) as conn:
        conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)", ("u1", now.isoformat()))
        for i in range(20):
            deadline = (now - timedelta(days=i + 1)).isoformat()
            conn.execute(
                """INSERT INTO tasks(task_id,user_id,title,deadline,priority,status,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (f"stale-{i}", "u1", f"Stale {i}", deadline,
                 "normal", "overdue", now.isoformat()),
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
    store.ensure_user("demo", declared_working_window_start="08:00",
                      declared_working_window_end="22:00")
    store.ensure_user("demo", declared_working_window_start="09:00",
                      declared_working_window_end="21:00")
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

    # type: ignore
    assert result["response_payload"]["tts_text"] == "You have one priority task."
    pending = result["pending_trace"]  # type: ignore
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

    assert result["pending_trace"]["trace_id"]  # type: ignore


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


# --- Phase 17 Phase 2: task mutations & reminder outcome -------------------


def _seed_pending_reminder(store, db_path, *, user_id="u1", trace_id=None,
                           dispatched_at=None):
    """Insert a synthetic 'pending' decision_trace row directly, matching
    the pattern scripts/seed_wp103.py already uses for lead_time_state.
    Phase 18 (the policy-tick scheduler) is what creates these rows for
    real; until it ships, tests seed them directly (Phase 2 plan note)."""
    from uuid import uuid4

    trace_id = trace_id or str(uuid4())
    dispatched_at = dispatched_at or datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
                     (user_id, dispatched_at.isoformat()))
        conn.execute(
            """
            INSERT INTO decision_trace(
                trace_id, session_id, user_id, timestamp, intent,
                intent_confidence, retrieved_context_ids, affect_level,
                deadline_proximity, policy_rule, action_taken, lead_time_min,
                reminder_outcome, degradation_reason, network_event,
                latency_ms, latency_basis
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trace_id, "sess-1", user_id, dispatched_at.isoformat(),
                "dismiss_reminder", 0.9, "[]", "Moderate", "imminent", "R5",
                "deliver", 15.0, "pending", None, None, 1.0,
                "host_observed_only",
            ),
        )
    return trace_id


def test_save_task_generates_task_id_and_persists_row(tmp_path):
    db_path = str(tmp_path / "tasks.db")
    store = SQLiteStore(db_path)
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Buy milk", priority="high")
    assert task_id
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, title, priority, status FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    assert row == ("u1", "Buy milk", "high", "pending")


def test_save_task_never_accepts_a_caller_supplied_id(tmp_path):
    """save_task's signature has no task_id parameter at all -- the id is
    always generated at the persistence boundary."""
    import inspect
    from storage.sqlite_store import SQLiteStore as _S
    assert "task_id" not in inspect.signature(_S.save_task).parameters


def test_reschedule_task_updates_exactly_one_row(tmp_path):
    db_path = str(tmp_path / "reschedule.db")
    store = SQLiteStore(db_path)
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Buy milk")
    new_deadline = datetime.now(timezone.utc) + timedelta(hours=2)

    assert store.reschedule_task("u1", task_id, new_deadline) is True
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT deadline FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    assert row[0] == new_deadline.isoformat()


def test_reschedule_task_is_user_scoped(tmp_path):
    db_path = str(tmp_path / "reschedule_scope.db")
    store = SQLiteStore(db_path)
    store.ensure_user("u1")
    store.ensure_user("u2")
    task_id = store.save_task("u1", "Buy milk")

    result = store.reschedule_task(
        "u2", task_id, datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert result is False
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT deadline FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    assert row[0] is None  # untouched


def test_reschedule_task_missing_task_returns_false(tmp_path):
    store = SQLiteStore(str(tmp_path / "missing.db"))
    store.ensure_user("u1")
    result = store.reschedule_task(
        "u1", "no-such-task", datetime.now(timezone.utc)
    )
    assert result is False


def _outcome_kwargs(**overrides):
    kwargs = dict(
        response_window_minutes=10,
        adaptive_lead_time_enabled=True,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15.0,
    )
    kwargs.update(overrides)
    return kwargs


def test_update_reminder_outcome_accepted_updates_in_place_same_trace_id(tmp_path):
    db_path = str(tmp_path / "accept.db")
    store = SQLiteStore(db_path)
    trace_id = _seed_pending_reminder(store, db_path)

    outcome = store.update_reminder_outcome(
        user_id="u1", trace_id=trace_id, outcome="accepted",
        **_outcome_kwargs(),
    )
    assert outcome.succeeded is True
    assert outcome.target_id == trace_id
    assert outcome.intent == "dismiss_reminder"

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT trace_id, reminder_outcome, lead_time_min FROM decision_trace "
            "WHERE user_id = ?", ("u1",),
        ).fetchall()
    assert len(rows) == 1  # in place, no duplicate row
    assert rows[0][0] == trace_id
    assert rows[0][1] == "accepted"
    assert rows[0][2] == 15.0  # accepted: L_hat == L, so L is unchanged


def test_update_reminder_outcome_snoozed_reaches_the_ema(tmp_path):
    db_path = str(tmp_path / "snooze.db")
    store = SQLiteStore(db_path)
    trace_id = _seed_pending_reminder(store, db_path)

    outcome = store.update_reminder_outcome(
        user_id="u1", trace_id=trace_id, outcome="snoozed", snooze_minutes=10,
        **_outcome_kwargs(),
    )
    assert outcome.succeeded is True
    assert outcome.snooze_minutes == 10  # not discarded

    expected_l = compute_lead_time_ema(
        15.0, "snoozed", 10, alpha=0.3, lo=5, hi=60)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT reminder_outcome, lead_time_min FROM decision_trace "
            "WHERE trace_id = ?", (trace_id,),
        ).fetchone()
        state_row = conn.execute(
            "SELECT current_L FROM lead_time_state WHERE user_id = ?", ("u1",),
        ).fetchone()
    assert row == ("snoozed", expected_l)
    assert state_row[0] == expected_l


def test_update_reminder_outcome_missing_trace_rejects(tmp_path):
    store = SQLiteStore(str(tmp_path / "missing_reminder.db"))
    store.ensure_user("u1")
    outcome = store.update_reminder_outcome(
        user_id="u1", trace_id="no-such-trace", outcome="accepted",
        **_outcome_kwargs(),
    )
    assert outcome.succeeded is False
    assert outcome.error_code == "reminder_not_found"


def test_update_reminder_outcome_not_pending_rejects(tmp_path):
    db_path = str(tmp_path / "not_pending.db")
    store = SQLiteStore(db_path)
    trace_id = _seed_pending_reminder(store, db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE decision_trace SET reminder_outcome = 'accepted' WHERE trace_id = ?",
            (trace_id,),
        )
    outcome = store.update_reminder_outcome(
        user_id="u1", trace_id=trace_id, outcome="accepted",
        **_outcome_kwargs(),
    )
    assert outcome.succeeded is False
    assert outcome.error_code == "reminder_not_pending"


def test_update_reminder_outcome_outside_response_window_rejects(tmp_path):
    db_path = str(tmp_path / "expired.db")
    store = SQLiteStore(db_path)
    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    trace_id = _seed_pending_reminder(store, db_path, dispatched_at=stale)

    outcome = store.update_reminder_outcome(
        user_id="u1", trace_id=trace_id, outcome="accepted",
        **_outcome_kwargs(response_window_minutes=10),
    )
    assert outcome.succeeded is False
    assert outcome.error_code == "reminder_not_pending"
    # Nothing was written -- rejection is clean, no partial commit.
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT reminder_outcome FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row[0] == "pending"


def test_update_reminder_outcome_wrong_user_rejects_as_not_found(tmp_path):
    db_path = str(tmp_path / "wrong_user.db")
    store = SQLiteStore(db_path)
    trace_id = _seed_pending_reminder(store, db_path, user_id="u1")
    store.ensure_user("u2")

    outcome = store.update_reminder_outcome(
        user_id="u2", trace_id=trace_id, outcome="accepted",
        **_outcome_kwargs(),
    )
    assert outcome.succeeded is False
    assert outcome.error_code == "reminder_not_found"  # no cross-user leak
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT reminder_outcome FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row[0] == "pending"  # untouched


def test_update_reminder_outcome_ema_exact_values_and_clamping(tmp_path):
    db_path = str(tmp_path / "ema.db")
    store = SQLiteStore(db_path)

    # accepted: L unchanged
    t1 = _seed_pending_reminder(store, db_path)
    out1 = store.update_reminder_outcome(
        user_id="u1", trace_id=t1, outcome="accepted", **_outcome_kwargs(),
    )
    with sqlite3.connect(db_path) as conn:
        l_after_accept = conn.execute(
            "SELECT current_L FROM lead_time_state WHERE user_id = ?", ("u1",)
        ).fetchone()[0]
    assert l_after_accept == 15.0

    # snoozed by 10 from L=15: L_hat=5, L=0.7*15+0.3*5=12.0
    t2 = _seed_pending_reminder(store, db_path)
    store.update_reminder_outcome(
        user_id="u1", trace_id=t2, outcome="snoozed", snooze_minutes=10,
        **_outcome_kwargs(),
    )
    with sqlite3.connect(db_path) as conn:
        l_after_snooze = conn.execute(
            "SELECT current_L FROM lead_time_state WHERE user_id = ?", ("u1",)
        ).fetchone()[0]
    assert l_after_snooze == pytest.approx(12.0)

    # a huge snooze must clamp to the floor (lo=5)
    t3 = _seed_pending_reminder(store, db_path)
    store.update_reminder_outcome(
        user_id="u1", trace_id=t3, outcome="snoozed", snooze_minutes=500,
        **_outcome_kwargs(),
    )
    with sqlite3.connect(db_path) as conn:
        l_after_huge_snooze = conn.execute(
            "SELECT current_L FROM lead_time_state WHERE user_id = ?", ("u1",)
        ).fetchone()[0]
    assert l_after_huge_snooze == 5.0


def test_update_reminder_outcome_adaptive_disabled_keeps_l_fixed(tmp_path):
    db_path = str(tmp_path / "fixed.db")
    store = SQLiteStore(db_path)
    trace_id = _seed_pending_reminder(store, db_path)

    outcome = store.update_reminder_outcome(
        user_id="u1", trace_id=trace_id, outcome="snoozed", snooze_minutes=10,
        **_outcome_kwargs(adaptive_lead_time_enabled=False),
    )
    assert outcome.succeeded is True
    with sqlite3.connect(db_path) as conn:
        trace_row = conn.execute(
            "SELECT lead_time_min FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        state_row = conn.execute(
            "SELECT current_L FROM lead_time_state WHERE user_id = ?", ("u1",),
        ).fetchone()
    assert trace_row[0] == 15.0  # fixed at the seeded/default L, not the EMA
    assert state_row is None  # untouched, not rewritten with the same value


def test_update_reminder_outcome_delivery_miss_is_rejected_outright(tmp_path):
    store = SQLiteStore(str(tmp_path / "no_delivery_miss.db"))
    store.ensure_user("u1")
    with pytest.raises(ValueError, match="scheduler"):
        store.update_reminder_outcome(
            user_id="u1", trace_id="whatever", outcome="delivery_miss",
            **_outcome_kwargs(),
        )
