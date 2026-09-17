"""Regression test for the decision_trace in-place schema migration.

storage/schema.py relaxes intent, intent_confidence, and affect_level from
NOT NULL to nullable so degraded traces (F4) can be written. CREATE TABLE IF
NOT EXISTS only creates missing tables -- it never alters a table that
already exists -- so a database file created before this change was left on
the old, stricter schema forever, with save_degraded_trace failing on every
such database:

    IntegrityError: NOT NULL constraint failed: decision_trace.intent

This test builds a database on the pre-relaxation ("main") schema, the way
an existing deployment's database file would look, then opens it through
this branch's code and confirms a degraded trace can be written and the
row that was already there survives the migration untouched.
"""

from __future__ import annotations

import sqlite3

import pytest

from storage.database import SQLiteDatabase
from storage.decision_trace import DecisionTraceRepository
from storage.schema import _migrate_decision_trace, initialize_schema

# The schema as it existed before degraded traces: intent, intent_confidence,
# and affect_level are all NOT NULL. Everything else matches the current
# schema, since the migration only needs to relax these three columns.
_OLD_SCHEMA_SQL = """
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    declared_working_window_start TEXT,
    declared_working_window_end TEXT
);

CREATE TABLE decision_trace (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT,
    user_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    intent TEXT NOT NULL,
    intent_confidence REAL NOT NULL,
    retrieved_context_ids TEXT,
    affect_level TEXT NOT NULL,
    deadline_proximity TEXT NOT NULL,
    policy_rule TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    lead_time_min REAL,
    reminder_outcome TEXT NOT NULL,
    degradation_reason TEXT,
    network_event TEXT,
    latency_ms REAL NOT NULL,
    latency_basis TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX ix_decision_trace_user_timestamp
    ON decision_trace(user_id, timestamp);
"""


def _build_old_schema_database(path: str) -> None:
    """Create a database file on the pre-relaxation schema, with one existing row."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_OLD_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)",
            ("u1", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO decision_trace (
                trace_id, session_id, user_id, timestamp, intent,
                intent_confidence, affect_level, deadline_proximity,
                policy_rule, action_taken, reminder_outcome, latency_ms,
                latency_basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "11111111-1111-1111-1111-111111111111", "s1", "u1",
                "2026-01-01T00:00:00+00:00", "add_task", 0.9, "Low",
                "not_imminent", "normal_delivery", "deliver", "delivered",
                42.0, "host_observed_only",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_relaxes_not_null_columns_on_an_existing_database(tmp_path):
    """PRAGMA table_info must show intent/intent_confidence/affect_level as
    nullable after opening an old-schema database file, not just on a fresh one.
    """
    db_path = str(tmp_path / "upgraded.db")
    _build_old_schema_database(db_path)

    db = SQLiteDatabase(db_path)
    with db.connection() as conn:
        initialize_schema(conn)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1]: row[3] for row in conn.execute(
            "PRAGMA table_info(decision_trace)")}
    assert columns["intent"] == 0
    assert columns["intent_confidence"] == 0
    assert columns["affect_level"] == 0


def test_save_degraded_trace_succeeds_against_an_upgraded_in_place_database(tmp_path):
    """The exact repro from review: open a main-schema database with this
    branch's code, then call save_degraded_trace. Must not raise.
    """
    db_path = str(tmp_path / "upgraded.db")
    _build_old_schema_database(db_path)

    db = SQLiteDatabase(db_path)
    with db.connection() as conn:
        initialize_schema(conn)

    repo = DecisionTraceRepository(db)
    repo.save_degraded(
        {
            "trace_id": "22222222-2222-2222-2222-222222222222",
            "session_id": None,
            "user_id": "u1",
            "timestamp": "2026-01-01T01:00:00+00:00",
            "degradation_reason": "session_timeout",
        }
    )

    rows = repo.list_for_user("u1")
    degraded = next(
        r for r in rows if r["trace_id"] == "22222222-2222-2222-2222-222222222222")
    assert degraded["intent"] is None
    assert degraded["deadline_proximity"] == "n/a"


def test_migration_preserves_the_row_that_already_existed(tmp_path):
    """The pre-existing row must survive the rebuild unchanged."""
    db_path = str(tmp_path / "upgraded.db")
    _build_old_schema_database(db_path)

    db = SQLiteDatabase(db_path)
    with db.connection() as conn:
        initialize_schema(conn)

    repo = DecisionTraceRepository(db)
    rows = repo.list_for_user("u1")
    original = next(
        r for r in rows if r["trace_id"] == "11111111-1111-1111-1111-111111111111")
    assert original["intent"] == "add_task"
    assert original["intent_confidence"] == 0.9
    assert original["affect_level"] == "Low"
    assert original["latency_ms"] == 42.0


def test_migration_failure_mid_rebuild_rolls_back_without_losing_rows(tmp_path):
    """A failure after the rename/create steps must leave the old table intact."""
    db_path = str(tmp_path / "upgraded.db")
    _build_old_schema_database(db_path)

    class FailingConnection(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._fail_once = True

        def execute(self, sql, parameters=()):
            if self._fail_once and sql.lstrip().upper().startswith("INSERT INTO DECISION_TRACE "):
                self._fail_once = False
                raise RuntimeError("injected migration failure")
            return super().execute(sql, parameters)

    conn = sqlite3.connect(db_path, factory=FailingConnection)
    try:
        with pytest.raises(RuntimeError, match="injected migration failure"):
            _migrate_decision_trace(conn)

        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "decision_trace" in table_names
        assert "decision_trace__pre_migration" not in table_names

        row = conn.execute(
            "SELECT trace_id, intent FROM decision_trace WHERE user_id = ?",
            ("u1",),
        ).fetchone()
        assert row == ("11111111-1111-1111-1111-111111111111", "add_task")
    finally:
        conn.close()


def test_migration_is_idempotent_across_repeated_initialize_schema_calls(tmp_path):
    """A second initialize_schema() call (e.g. a second process start) against
    an already-migrated database must not re-trigger the rebuild or error.
    """
    db_path = str(tmp_path / "upgraded.db")
    _build_old_schema_database(db_path)

    db = SQLiteDatabase(db_path)
    with db.connection() as conn:
        initialize_schema(conn)
    with db.connection() as conn:
        initialize_schema(conn)  # must be a no-op, not raise

    repo = DecisionTraceRepository(db)
    rows = repo.list_for_user("u1")
    assert len(rows) == 1


def test_fresh_database_is_unaffected_by_the_migration_path(tmp_path):
    """A brand-new database (no pre-existing decision_trace table) must be
    created directly by CREATE TABLE IF NOT EXISTS, with the migration a no-op.
    """
    db_path = str(tmp_path / "fresh.db")
    db = SQLiteDatabase(db_path)
    with db.connection() as conn:
        initialize_schema(conn)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1]: row[3] for row in conn.execute(
            "PRAGMA table_info(decision_trace)")}
    assert columns["intent"] == 0
    assert columns["intent_confidence"] == 0
    assert columns["affect_level"] == 0
