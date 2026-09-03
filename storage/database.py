"""SQLite connection lifecycle for the SYNCRO host."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteDatabase:
    """Own database path handling, connections, and SQLite pragmas."""

    def __init__(self, db_path: str) -> None:
        self.path = db_path
        if db_path != ":memory:":
            parent = Path(db_path).expanduser().parent
            parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """Open a configured connection. Caller owns and closes the connection."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
