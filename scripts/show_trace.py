"""Rebuild one interaction's timeline from a JSONL event log (OBS-LOG acceptance #11).

    python -m scripts.show_trace <trace_id> [--file logs/syncro-events.jsonl]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_trace(path: Path, trace_id: str) -> list[dict]:
    events = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn or foreign line must not hide the rest
            if record.get("trace_id") == trace_id:
                events.append(record)
    return sorted(events, key=lambda r: r["timestamp"])


def render(events: list[dict]) -> str:
    if not events:
        return "no events found for that trace_id"
    from datetime import datetime

    t0 = datetime.fromisoformat(events[0]["timestamp"])
    rows = []
    for e in events:
        offset = (datetime.fromisoformat(e["timestamp"]) - t0).total_seconds() * 1000
        dur = f"{e['duration_ms']:.1f}ms" if e.get("duration_ms") is not None else ""
        err = f"  !! {e['error']['error_type']}: {e['error']['message']}" if e.get("error") else ""
        meta = json.dumps(e.get("metadata") or {}, separators=(",", ":"), default=str)
        rows.append(
            f"+{offset:8.1f}ms  {e['severity']:<8} {e['component']:<12} "
            f"{e['event_type']:<24} {e['status']:<8} {dur:>10}  {meta if meta != '{}' else ''}{err}"
        )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_id")
    parser.add_argument("--file", default=None, help="JSONL path (default: LOG_FILE_PATH)")
    args = parser.parse_args()
    path = args.file
    if path is None:
        from config.settings import get_settings

        path = get_settings().log_file_path
    if not path or not Path(path).exists():
        print(f"log file not found: {path!r} (use --file)", file=sys.stderr)
        return 2
    print(render(load_trace(Path(path), args.trace_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
