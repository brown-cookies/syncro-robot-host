"""LIVE interactive session: open item 4 -- runtime failure representation.

You control whether the storage layer is "healthy" or "flaky" (raising an
unexpected `sqlite3.OperationalError`, simulating a locked database), and
you issue `add_task` / `reschedule_task` commands yourself against the REAL
`pipeline.executor.ActionExecutor`. You can also flip to a `legacy` failure
boundary to compare, live, on your own inputs.

Run:
    python -m scripts.live_open_item_4_runtime_failure

Commands:
    flaky on | flaky off      toggle whether storage calls raise
    boundary fixed | boundary legacy_none | boundary legacy_generic
                               choose which failure boundary handles it:
                               fixed         = current ActionExecutor.execute
                               legacy_none   = no try/except at all (may crash!)
                               legacy_generic = catches everything, returns
                                                a blank "something went wrong"
    addtask <title>            run an add_task turn
    list                       list current tasks
    quit                       exit
"""

from __future__ import annotations

import shlex
import sqlite3
import tempfile
from typing import Any

from pipeline.contracts import AddTaskSlots
from pipeline.executor import ActionExecutor
from storage.sqlite_store import SQLiteStore

USER_ID = "u1"
HELP = __doc__.split("Commands")[1]


class FlakyStore:
    """Wraps a real SQLiteStore; `save_task` raises when `flaky` is True,
    simulating an unexpected infra failure rather than an input problem."""

    def __init__(self, inner: SQLiteStore):
        self._inner = inner
        self.flaky = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def save_task(self, *args, **kwargs):
        if self.flaky:
            raise sqlite3.OperationalError("database is locked")
        return self._inner.save_task(*args, **kwargs)


def legacy_execute_no_boundary(store, user_id: str, slots: dict[str, Any]):
    validated = AddTaskSlots.model_validate(slots)
    return store.save_task(
        user_id, validated.title,
        deadline=validated.deadline, notes=validated.notes,
        priority=validated.priority,
    )


def legacy_execute_generic_boundary(store, user_id: str, slots: dict[str, Any]):
    try:
        validated = AddTaskSlots.model_validate(slots)
        task_id = store.save_task(
            user_id, validated.title,
            deadline=validated.deadline, notes=validated.notes,
            priority=validated.priority,
        )
        return f"ok: {task_id}"
    except Exception:  # noqa: BLE001 - demo of the rejected shortcut
        return "something went wrong"


def list_tasks(store):
    with store.database.connection() as conn:
        rows = conn.execute(
            "SELECT task_id, title FROM tasks WHERE user_id = ?", (USER_ID,)
        ).fetchall()
    return [(r["task_id"], r["title"]) for r in rows]


def main():
    print("=" * 78)
    print("LIVE SESSION -- open item 4: runtime failure representation")
    print("=" * 78)
    print(HELP)

    tmp = tempfile.TemporaryDirectory()
    real_store = SQLiteStore(f"{tmp.name}/live.db")
    real_store.ensure_user(USER_ID)
    flaky_store = FlakyStore(real_store)
    executor = ActionExecutor(
        flaky_store,
        reminder_response_window_minutes=10,
        adaptive_lead_time_enabled=True,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )
    boundary = "fixed"
    print(f"flaky = {flaky_store.flaky}   boundary = {boundary}\n")

    while True:
        try:
            raw = input(f"(item4:{boundary}{'*flaky*' if flaky_store.flaky else ''}) > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            print(f"  parse error: {exc}")
            continue
        cmd, *rest = parts

        if cmd in ("quit", "exit"):
            break
        if cmd == "help":
            print(HELP)
            continue
        if cmd == "flaky":
            if not rest or rest[0] not in ("on", "off"):
                print("  usage: flaky on | flaky off")
                continue
            flaky_store.flaky = rest[0] == "on"
            print(f"  flaky = {flaky_store.flaky}")
            continue
        if cmd == "boundary":
            if not rest or rest[0] not in ("fixed", "legacy_none", "legacy_generic"):
                print("  usage: boundary fixed | boundary legacy_none | boundary legacy_generic")
                continue
            boundary = rest[0]
            print(f"  boundary = {boundary}")
            continue
        if cmd == "list":
            for task_id, title in list_tasks(real_store):
                print(f"  {task_id}  {title!r}")
            continue
        if cmd == "addtask":
            if not rest:
                print("  usage: addtask <title>")
                continue
            title = " ".join(rest)
            slots = {"title": title}

            if boundary == "fixed":
                outcome = executor.execute({
                    "user_id": USER_ID, "intent": "add_task", "slots": slots,
                })
                print(f"  ExecutionOutcome(succeeded={outcome.succeeded}, "
                      f"target_id={outcome.target_id}, error_code={outcome.error_code}, "
                      f"detail={outcome.detail!r})")
            elif boundary == "legacy_none":
                try:
                    task_id = legacy_execute_no_boundary(flaky_store, USER_ID, slots)
                    print(f"  (no exception) task_id = {task_id}")
                except Exception as exc:
                    print(f"  UNCAUGHT {type(exc).__name__}: {exc}")
                    print("  -> this would have propagated out of the executor")
                    print("     entirely; no ExecutionOutcome was ever produced.")
            else:  # legacy_generic
                result = legacy_execute_generic_boundary(flaky_store, USER_ID, slots)
                print(f"  result = {result!r}")
                if result == "something went wrong":
                    print("  -> no error code, no exception type, no message.")
            continue

        print(f"  unknown command: {cmd!r} (type `help`)")

    tmp.cleanup()
    print("Session ended.")


if __name__ == "__main__":
    main()
