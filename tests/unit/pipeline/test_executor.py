from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pipeline.executor import ActionExecutor
from storage.sqlite_store import SQLiteStore


def make_executor(store, *, adaptive=True):
    return ActionExecutor(
        store,
        reminder_response_window_minutes=10,
        adaptive_lead_time_enabled=adaptive,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )


def seed_pending_reminder(store, *, user_id="u1", trace_id=None):
    trace_id = trace_id or str(uuid4())
    now = datetime.now(timezone.utc)
    store.ensure_user(user_id)
    with store.database.connection() as conn:
        conn.execute(
            """
            INSERT INTO decision_trace(
                trace_id, session_id, user_id, timestamp, intent,
                intent_confidence, retrieved_context_ids, affect_level,
                deadline_proximity, policy_rule, action_taken, lead_time_min,
                reminder_outcome, degradation_reason, network_event,
                latency_ms, latency_basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                "reminder-session",
                user_id,
                now.isoformat(),
                "request_summary",
                0.99,
                "[]",
                "Moderate",
                "not_imminent",
                "R2",
                "defer",
                15.0,
                "pending",
                None,
                None,
                1.0,
                "host_observed_only",
            ),
        )
    return trace_id


def test_add_task_creates_real_row_and_returns_generated_id(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "add_task",
        "slots": {
            "title": "Submit thesis draft",
            "deadline": "2026-09-24T09:00:00+08:00",
            "priority": "high",
        },
    })

    assert outcome.succeeded is True
    assert outcome.intent == "add_task"
    assert outcome.target_id
    assert outcome.error_code is None

    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT task_id, user_id, title, deadline, priority FROM tasks WHERE task_id = ?",
            (outcome.target_id,),
        ).fetchone()
    assert row is not None
    assert tuple(row) == (
        outcome.target_id,
        "u1",
        "Submit thesis draft",
        "2026-09-24T09:00:00+08:00",
        "high",
    )


def test_add_task_rejects_whitespace_only_title(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "add_task",
        "slots": {"title": "   \t  "},
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "invalid_slots"
    with store.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_add_task_invalid_slots_never_mutates_storage(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "add_task",
        "slots": {"title": ""},
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "invalid_slots"
    with store.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_reschedule_task_resolves_exact_title_from_pre_mutation_context(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    task_id = store.save_task(
        "u1", "Team meeting", deadline=datetime(2026, 9, 25, 9, tzinfo=timezone.utc)
    )
    executor = make_executor(store)

    context = {
        "tasks": [{
            "task_id": task_id,
            "title": "Team meeting",
            "deadline": "2026-09-25T09:00:00+00:00",
            "priority": "normal",
            "status": "pending",
        }],
        "overdue_tasks": [],
        "recent_routine": None,
    }
    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "  TEAM   meeting ",
            "new_deadline": "2026-09-26T14:30:00+00:00",
        },
        "context": context,
    })

    assert outcome.succeeded is True
    assert outcome.target_id == task_id
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT deadline FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    assert row[0] == "2026-09-26T14:30:00+00:00"


def test_reschedule_task_not_found_does_not_touch_storage(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Existing task")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "Missing task",
            "new_deadline": "2026-09-26T14:30:00+00:00",
        },
        "context": {
            "tasks": [{"task_id": task_id, "title": "Existing task"}],
            "overdue_tasks": [],
        },
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "task_not_found"
    with store.database.connection() as conn:
        assert conn.execute(
            "SELECT deadline FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()[0] is None


def test_reschedule_task_ambiguous_reference_does_not_guess(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    t1 = store.save_task("u1", "Call John")
    t2 = store.save_task("u1", "Call John")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "Call John",
            "new_deadline": "2026-09-26T14:30:00+00:00",
        },
        "context": {
            "tasks": [
                {"task_id": t1, "title": "Call John"},
                {"task_id": t2, "title": "Call John"},
            ],
            "overdue_tasks": [],
        },
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "ambiguous_task"


def test_snooze_reminder_updates_existing_trace_and_ema(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    trace_id = seed_pending_reminder(store)
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "snooze_reminder",
        "slots": {"reference_trace_id": trace_id, "snooze_minutes": 10},
    })

    assert outcome.succeeded is True
    assert outcome.target_id == trace_id
    assert outcome.snooze_minutes == 10
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT reminder_outcome, lead_time_min FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row[0] == "snoozed"
    assert row[1] == 12.0


def test_dismiss_reminder_requires_explicit_reference(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "slots": {},
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "invalid_slots"


def test_dismiss_reminder_updates_referenced_pending_trace(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    trace_id = seed_pending_reminder(store)
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "slots": {"reference_trace_id": trace_id},
    })

    assert outcome.succeeded is True
    assert outcome.target_id == trace_id
    assert outcome.snooze_minutes is None
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT reminder_outcome, lead_time_min FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row[0] == "accepted"
    assert row[1] == 15.0


def test_executor_uses_same_store_instance_passed_at_construction(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    executor = make_executor(store)
    assert executor.store is store
