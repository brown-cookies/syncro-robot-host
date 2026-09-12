"""S3 regression: SQLite connections must be safe for more than one writer.

WP-105 introduces a worker thread writing decision traces alongside FastAPI's
own request-handling writers, so more than one writer becomes possible for the
first time. SQLite's default rollback-journal mode holds an exclusive lock for
the duration of a write transaction; with the default 5s busy timeout already
in play but no WAL, the first overlapping write during a demo surfaces as
`sqlite3.OperationalError: database is locked` (finding S3).
"""

from __future__ import annotations

from storage.database import SQLiteDatabase


def test_connect_enables_wal_journal_mode(tmp_path):
    """A fresh connection must report WAL, not the SQLite default (delete/rollback)."""
    db = SQLiteDatabase(str(tmp_path / "test.db"))
    with db.connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal"


def test_connect_sets_a_nonzero_busy_timeout(tmp_path):
    """A fresh connection must retry on lock contention instead of failing immediately.

    Note: this currently passes even without the explicit PRAGMA in
    SQLiteDatabase.connect(), because Python's sqlite3.connect() already applies
    a 5s busy timeout by default. The assertion (and the explicit PRAGMA it
    guards) exist so this is a decision this module states and owns rather than
    an incidental default that a future change could silently alter.
    """
    db = SQLiteDatabase(str(tmp_path / "test.db"))
    with db.connection() as conn:
        busy_timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert busy_timeout_ms > 0


def test_wal_mode_persists_across_a_second_connection(tmp_path):
    """WAL is a per-file setting; a second connection to the same file must still
    see it, not just the connection that first set it.
    """
    db = SQLiteDatabase(str(tmp_path / "test.db"))
    with db.connection():
        pass  # first connection establishes the file and sets WAL

    with db.connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal"


def test_foreign_keys_still_enforced(tmp_path):
    """S3 must not weaken the existing foreign_keys pragma while adding WAL."""
    db = SQLiteDatabase(str(tmp_path / "test.db"))
    with db.connection() as conn:
        foreign_keys_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert foreign_keys_on == 1
