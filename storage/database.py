"""SQLite connection lifecycle for the SYNCRO host."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteDatabase:
    """Own database path handling, connections, and SQLite pragmas."""

    def __init__(self, db_path: str) -> None:
        """Initialize the SQLiteDatabase and establish its runtime state."""
        self.path = db_path
        if db_path != ":memory:":
            parent = Path(db_path).expanduser().parent
            parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """Open a database connection using the configured storage settings."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL lets readers and writers proceed concurrently instead of blocking
        # on SQLite's default rollback-journal exclusive lock. WP-105 adds a
        # worker thread writing traces alongside FastAPI's own writers, so more
        # than one writer becomes possible for the first time (finding S3).
        # journal_mode=WAL is a per-file setting (persists in the database file
        # itself after the first connection sets it) but is re-issued on every
        # connect() here since that has no cost and removes any ordering
        # dependency on which connection opens first. It is a no-op for
        # ":memory:" databases, which have no file to hold WAL's separate log.
        conn.execute("PRAGMA journal_mode = WAL")
        # Known trade-off: WAL mode means committed writes can sit in the
        # `-wal` sidecar file (with `-shm` as its shared-memory index) rather
        # than in `self.path` itself until SQLite checkpoints them back into
        # the main file. Any backup or deletion that operates on `self.path`
        # alone -- a plain file copy, or removing just the `.db` file -- can
        # therefore miss committed data still sitting in `-wal`/`-shm`, which
        # matters for NFR-11's deletion guarantee. Callers doing either must
        # either checkpoint first (`PRAGMA wal_checkpoint(TRUNCATE)`) or
        # include the `-wal`/`-shm` sidecar files alongside `self.path`.
        # sqlite3.connect() already applies a 5s busy timeout by default (its
        # own `timeout` parameter, which defaults to 5.0s and is not the same
        # setting as this PRAGMA, though it has the same effect at this value).
        # This line changes no observed behaviour today; it exists so the
        # timeout is a decision this module owns and states explicitly, not an
        # incidental default inherited from the sqlite3 module that a future
        # change (e.g. passing an explicit `timeout=` to connect(), or a driver
        # swap) could silently alter.
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Provide a database connection and close it reliably after use."""
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()
