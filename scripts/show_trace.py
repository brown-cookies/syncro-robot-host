"""Rebuild one interaction's timeline from a JSONL event log (OBS-LOG acceptance #11).

    python -m scripts.show_trace --list              # recent traces, newest first
    python -m scripts.show_trace --last              # timeline of the most recent trace
    python -m scripts.show_trace <trace_id>          # timeline of one trace
    ... add --file <path> to read a different log (default: LOG_FILE_PATH)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def _records(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn or foreign line must not hide the rest
            if isinstance(record, dict) and record.get("trace_id"):
                yield record


def load_trace(path: Path, trace_id: str) -> list[dict]:
    events = [r for r in _records(path) if r["trace_id"] == trace_id]
    return sorted(events, key=lambda r: r["timestamp"])


def list_traces(path: Path) -> list[dict]:
    """One summary row per trace, newest first."""
    traces: dict[str, dict] = {}
    for r in _records(path):
        t = traces.setdefault(
            r["trace_id"],
            {"trace_id": r["trace_id"], "started": r["timestamp"], "session_id": r.get("session_id"),
             "events": 0, "failed": False, "completed": False},
        )
        t["events"] += 1
        t["started"] = min(t["started"], r["timestamp"])
        t["session_id"] = t["session_id"] or r.get("session_id")
        if r["event_type"] == "interaction_failed" or r["severity"] in ("ERROR", "CRITICAL"):
            t["failed"] = True
        if r["event_type"] == "interaction_completed":
            t["completed"] = True
    for t in traces.values():
        t["outcome"] = "FAILED" if t["failed"] else (
            "ok" if t["completed"] else "incomplete")
    return sorted(traces.values(), key=lambda t: t["started"], reverse=True)


def render_list(rows: list[dict], limit: int = 20) -> str:
    if not rows:
        return "no traces found in that log"
    lines = [f"{'started (UTC)':<20} {'outcome':<10} {'events':>6}  trace_id"]
    for t in rows[:limit]:
        lines.append(
            f"{t['started'][:19].replace('T', ' '):<20} {t['outcome']:<10} {t['events']:>6}  {t['trace_id']}")
    return "\n".join(lines)


def render(events: list[dict]) -> str:
    if not events:
        return "no events found for that trace_id"
    t0 = datetime.fromisoformat(events[0]["timestamp"])
    rows = []
    for e in events:
        offset = (datetime.fromisoformat(
            e["timestamp"]) - t0).total_seconds() * 1000
        dur = f"{e['duration_ms']:.1f}ms" if e.get(
            "duration_ms") is not None else ""
        err = f"  !! {e['error']['error_type']}: {e['error']['message']}" if e.get(
            "error") else ""
        meta = json.dumps(e.get("metadata") or {},
                          separators=(",", ":"), default=str)
        rows.append(
            f"+{offset:8.1f}ms  {e['severity']:<8} {e['component']:<12} "
            f"{e['event_type']:<24} {e['status']:<8} {dur:>10}  {meta if meta != '{}' else ''}{err}"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("trace_id", nargs="?", help="exact trace_id to show")
    parser.add_argument("--list", action="store_true",
                        help="list recent traces, newest first")
    parser.add_argument("--last", action="store_true",
                        help="show the most recent trace")
    parser.add_argument("--limit", type=int, default=20,
                        help="rows for --list (default 20)")
    parser.add_argument("--file", default=None,
                        help="JSONL path (default: LOG_FILE_PATH)")
    args = parser.parse_args(argv)

    path = args.file
    if path is None:
        from config.settings import get_settings

        path = get_settings().log_file_path
    if not path or not Path(path).exists():
        print(
            f"log file not found: {path!r} (set LOG_OUTPUT=file, or use --file)", file=sys.stderr)
        return 2
    path = Path(path)

    if args.list:
        print(render_list(list_traces(path), args.limit))
        return 0
    trace_id = args.trace_id
    rows = list_traces(path)
    if args.last:
        if not rows:
            print("no traces found in that log", file=sys.stderr)
            return 1
        trace_id = rows[0]["trace_id"]
    if not trace_id:
        parser.error("give a trace_id, or use --last / --list")
    # Always name the trace, so the timeline can be matched to decision_trace.trace_id.
    outcome = next((r["outcome"] for r in rows if r["trace_id"] == trace_id), "not found")
    print(f"# {trace_id}  ({outcome})")
    print(render(load_trace(path, trace_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
