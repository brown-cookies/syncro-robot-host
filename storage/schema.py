"""SQLite DDL matching ``techdocs/SPEC.md`` Section 9."""

from __future__ import annotations

import sqlite3


# Keep all CREATE TABLE / CREATE INDEX statements in this module so the
# database schema has one explicit source of truth. Repository modules must
# contain queries and persistence operations, not DDL.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    declared_working_window_start TEXT,
    declared_working_window_end TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    deadline TEXT,
    notes TEXT,
    priority TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'overdue', 'completed')),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    client_write_id TEXT UNIQUE,
    source TEXT,
    external_id TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_source_external_id
    ON tasks(source, external_id)
    WHERE source IS NOT NULL AND external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_tasks_user_deadline
    ON tasks(user_id, deadline);

CREATE TABLE IF NOT EXISTS routine_log (
    log_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('break', 'routine')),
    logged_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS ix_routine_log_user_logged_at
    ON routine_log(user_id, logged_at DESC);

CREATE TABLE IF NOT EXISTS decision_trace (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    intent TEXT NOT NULL,
    intent_confidence REAL NOT NULL,
    retrieved_context_ids TEXT NOT NULL,
    affect_level TEXT NOT NULL,
    deadline_proximity TEXT NOT NULL,
    policy_rule TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    lead_time_min REAL NOT NULL,
    reminder_outcome TEXT NOT NULL,
    degradation_reason TEXT,
    network_event TEXT,
    latency_ms REAL NOT NULL,
    latency_basis TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS ix_decision_trace_user_timestamp
    ON decision_trace(user_id, timestamp);

CREATE TABLE IF NOT EXISTS lead_time_state (
    user_id TEXT PRIMARY KEY,
    current_L REAL NOT NULL,
    last_updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS activity_buckets (
    bucket_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    minute_start TEXT NOT NULL,
    active_seconds INTEGER NOT NULL,
    idle_seconds INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, minute_start)
);

CREATE TABLE IF NOT EXISTS consent_records (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    client_write_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS self_reports (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    client_write_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS exit_survey_responses (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    client_write_id TEXT NOT NULL UNIQUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS outages (
    outage_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    affected_interaction_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS deletion_receipts (
    user_id TEXT PRIMARY KEY,
    requested_at TEXT NOT NULL,
    client_write_id TEXT NOT NULL UNIQUE,
    tables_cleared TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create all required tables and indexes idempotently."""
    conn.executescript(SCHEMA_SQL)
