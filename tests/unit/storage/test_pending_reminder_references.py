from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from storage.sqlite_store import SQLiteStore


def seed_pending(store, *, user_id, task_id, timestamp):
    trace_id = str(uuid4())
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
                trace_id, "s1", user_id, timestamp.isoformat(), "request_summary",
                0.95, f'["{task_id}"]', "Moderate", "not_imminent", "R2",
                "defer", 15.0, "pending", None, None, 1.0,
                "host_observed_only",
            ),
        )
    return trace_id


def test_pending_reference_uses_task_title_label(tmp_path):
    store = SQLiteStore(str(tmp_path / "references.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Submit thesis")
    trace_id = seed_pending(
        store,
        user_id="u1",
        task_id=task_id,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    candidates = store.list_pending_reminder_references(
        "u1", response_window_minutes=10
    )

    assert [item.trace_id for item in candidates] == [trace_id]
    assert candidates[0].title == "Submit thesis"
    assert "Submit thesis" in candidates[0].label


def test_pending_reference_uses_exclusive_response_window(tmp_path):
    store = SQLiteStore(str(tmp_path / "window.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Submit thesis")
    seed_pending(
        store,
        user_id="u1",
        task_id=task_id,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=10),
    )

    candidates = store.list_pending_reminder_references(
        "u1", response_window_minutes=10
    )

    assert candidates == []


def test_pending_reference_rejects_future_timestamp(tmp_path):
    store = SQLiteStore(str(tmp_path / "future.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Submit thesis")
    seed_pending(
        store,
        user_id="u1",
        task_id=task_id,
        timestamp=datetime.now(timezone.utc) + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="future reminder timestamp"):
        store.list_pending_reminder_references(
            "u1", response_window_minutes=10
        )
