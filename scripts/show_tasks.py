"""Console task table: print tasks and the ingest audit log.

Run against the real database after a `curl` to the running host:
    python -m scripts.show_tasks            # uses DB_PATH / ./syncro.db
    python -m scripts.show_tasks --db path/to/other.db
"""

from __future__ import annotations

import argparse

from config.settings import get_settings
from storage.sqlite_store import SQLiteStore


def format_tasks(tasks: list[dict]) -> str:
    """Render tasks as a fixed-width console table."""
    header = f"{'source':<14}{'external_id':<14}{'title':<32}{'priority':<9}{'status':<9}deadline"
    lines = [header, "-" * len(header)]
    for t in tasks:
        lines.append(
            f"{(t['source'] or '-'):<14}{(t['external_id'] or '-'):<14}"
            f"{t['title'][:30]:<32}{t['priority']:<9}{t['status']:<9}{t['deadline'] or '-'}"
        )
    if not tasks:
        lines.append("(no tasks)")
    return "\n".join(lines)


def format_events(events: list[dict]) -> str:
    """Render the ingest audit log."""
    lines = ["ingress_event_log:"]
    for e in events:
        lines.append(f"  {e['logged_at']}  source={e['source']}  "
                     f"external_id={e['external_id']}  outcome={e['outcome']}")
    if not events:
        lines.append("  (no ingest events)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="SQLite path (default: DB_PATH)")
    args = parser.parse_args()
    store = SQLiteStore(args.db or get_settings().db_path)
    print(format_tasks(store.list_tasks()))
    print()
    print(format_events(store.list_ingress_events()))


if __name__ == "__main__":
    main()
