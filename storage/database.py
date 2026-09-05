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
