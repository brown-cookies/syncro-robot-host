"""SQLite DDL matching ``techdocs/SPEC.md`` Section 9."""

from __future__ import annotations

import sqlite3


# Keep all CREATE TABLE / CREATE INDEX statements in this module so the
# database schema has one explicit source of truth. Repository modules must
# contain queries and persistence operations, not DDL.

# decision_trace's column list is shared between the normal CREATE TABLE IF
# NOT EXISTS below and the guarded rebuild in _migrate_decision_trace(),
# which needs the exact same column set (minus "IF NOT EXISTS") to recreate
# the table under the current, nullable-friendly definition. Keeping one
# copy avoids the two ever drifting apart.
DECISION_TRACE_COLUMNS = (
    "trace_id", "session_id", "user_id", "timestamp", "intent",
    "intent_confidence", "retrieved_context_ids", "affect_level",
    "deadline_proximity", "policy_rule", "action_taken", "lead_time_min",
    "reminder_outcome", "degradation_reason", "network_event", "latency_ms",
    "latency_basis",
)

_DECISION_TRACE_COLUMNS_SQL = """    trace_id TEXT PRIMARY KEY,
    session_id TEXT,
    user_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    intent TEXT,
    intent_confidence REAL,
    retrieved_context_ids TEXT,
    affect_level TEXT,
    deadline_proximity TEXT NOT NULL,
    policy_rule TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    lead_time_min REAL,
    reminder_outcome TEXT NOT NULL,
    degradation_reason TEXT,
    network_event TEXT,
    latency_ms REAL NOT NULL,
    latency_basis TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)"""

# Columns that used to be NOT NULL under the pre-degraded-trace schema and
# are the ones _decision_trace_needs_migration() checks. A database created
# before degraded-trace support still has all of these as NOT NULL, which
# rejects the NULLs a degraded trace (F4) must be able to write.
_FORMERLY_NOT_NULL_COLUMNS = frozenset(
    {"intent", "intent_confidence", "affect_level"})

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
{decision_trace_columns}
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

-- SPEC 6.1a: every accepted ingest call (created or duplicate) is auditable
-- with the connector's source id. Not user-scoped: ingested tasks are not tied
-- to a study participant.
CREATE TABLE IF NOT EXISTS ingress_event_log (
    event_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('created', 'duplicate')),
    task_id TEXT,
    logged_at TEXT NOT NULL
);
""".format(decision_trace_columns=_DECISION_TRACE_COLUMNS_SQL)


def _decision_trace_needs_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing decision_trace table still on the old NOT NULL schema.

    Returns False both when there is no decision_trace table yet (fresh
    database -- SCHEMA_SQL's CREATE TABLE IF NOT EXISTS will create it
    correctly on its own) and when it already matches the current schema
    (already migrated, or created fresh by this codebase already).
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'decision_trace'"
    ).fetchone()
    if row is None:
        return False

    for _cid, name, _col_type, notnull, _default, _pk in conn.execute(
        "PRAGMA table_info(decision_trace)"
    ):
        if name in _FORMERLY_NOT_NULL_COLUMNS and notnull:
            return True
    return False


def _migrate_decision_trace(conn: sqlite3.Connection) -> None:
    """Rebuild decision_trace in place so intent/intent_confidence/affect_level
    become nullable, preserving every existing row, index, and the table's
    original name.

    SQLite has no ALTER COLUMN, so this is the standard rebuild sequence:
    rename the old table out of the way, create the table fresh under the
    current (nullable) definition, copy the data across by explicit column
    name, then drop the renamed original. ix_decision_trace_user_timestamp
    is dropped automatically when its table is renamed/dropped; SCHEMA_SQL's
    own CREATE INDEX IF NOT EXISTS (run right after this, from
    initialize_schema) recreates it.

    Only called after _decision_trace_needs_migration() confirms an
    old-schema table exists, so this never runs against a fresh database.
    """
    conn.execute("BEGIN")
    try:
        conn.execute(
            "ALTER TABLE decision_trace RENAME TO decision_trace__pre_migration")
        conn.execute(
            f"CREATE TABLE decision_trace (\n{_DECISION_TRACE_COLUMNS_SQL}\n)")

        old_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(decision_trace__pre_migration)")
        }
        # Copy only columns the old table actually has; a database from any
        # earlier point in the schema's history is still handled rather than
        # assuming today's exact column set was already present.
        copy_columns = [c for c in DECISION_TRACE_COLUMNS if c in old_columns]
        columns_sql = ", ".join(copy_columns)
        conn.execute(
            f"INSERT INTO decision_trace ({columns_sql}) "
            f"SELECT {columns_sql} FROM decision_trace__pre_migration"
        )
        conn.execute("DROP TABLE decision_trace__pre_migration")
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the required database schema and indexes idempotently.

    Also upgrades a decision_trace table left over from before degraded
    traces existed: CREATE TABLE IF NOT EXISTS below only creates missing
    tables, it never relaxes a NOT NULL constraint on a table that is
    already there, so an in-place-upgraded database would otherwise keep
    rejecting every degraded trace (NOT NULL constraint failed on intent)
    forever. The migration runs first so the fresh-database case still goes
    through the normal CREATE TABLE IF NOT EXISTS path unchanged.
    """
    if _decision_trace_needs_migration(conn):
        _migrate_decision_trace(conn)
    conn.executescript(SCHEMA_SQL)
