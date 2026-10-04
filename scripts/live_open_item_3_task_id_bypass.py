"""LIVE interactive session: open item 3 -- reschedule target authority.

You seed tasks and issue reschedule commands yourself, in real time, against
a real (temp) SQLite store. By default every command runs through the
REAL, fixed `pipeline.executor.ActionExecutor`. You can flip a switch to
run the exact same commands through a reconstruction of the pre-fix
executor method instead, so you can compare live, on your own inputs, not
a canned scenario.

Run:
    python -m scripts.live_open_item_3_task_id_bypass

Commands:
    addtask <title>                     create a task, prints its task_id
    list                                list current tasks with id/deadline
    mode fixed | mode legacy            switch which executor path runs
    reschedule ref=<text|-> id=<id|-> deadline=<iso>
                                         run a reschedule_task turn with the
                                         given task_reference / task_id
                                         (use `-` for "omit this slot")
    quit                                exit
"""

from __future__ import annotations

import shlex
import tempfile
from typing import Any

from pipeline.contracts import ExecutionOutcome, RescheduleTaskSlots
from pipeline.deadline_parser import DeadlineParseError, parse_deadline
from pipeline.executor import ActionExecutor
from storage.sqlite_store import SQLiteStore

USER_ID = "u1"
HELP = __doc__.split("Commands")[1]


def legacy_execute_reschedule_task(
    executor: ActionExecutor, user_id: str, raw_slots: dict[str, Any], state: dict[str, Any]
) -> ExecutionOutcome:
    """Reconstruction of ActionExecutor._execute_reschedule_task exactly as
    it existed before the open item 3 fix."""
    raw_reference = raw_slots.get("task_reference")
    raw_task_id = raw_slots.get("task_id")

    if isinstance(raw_task_id, str) and raw_task_id.strip() and raw_reference is None:
        task_id = raw_task_id.strip()
    else:
        if not isinstance(raw_reference, str) or not raw_reference.strip():
            return executor._failure(
                "reschedule_task", "invalid_slots",
                "reschedule_task requires an explicit task_reference",
            )
        task_id = executor._resolve_task_reference(raw_reference, state.get("context", {}))
        if task_id is None:
            return executor._failure(
                "reschedule_task", "task_not_found",
                f"no task matches reference {raw_reference!r}",
            )

    try:
        parsed_deadline = parse_deadline(raw_slots.get("new_deadline"))
        slots = RescheduleTaskSlots(task_id=task_id, new_deadline=parsed_deadline)
    except (DeadlineParseError, Exception) as exc:  # noqa: BLE001 - demo only
        return executor._failure("reschedule_task", "invalid_slots", str(exc))

    updated = executor.store.reschedule_task(user_id, slots.task_id, slots.new_deadline)
    if not updated:
        return executor._failure(
            "reschedule_task", "task_not_found",
            f"task {slots.task_id!r} was not found for this user",
        )
    return ExecutionOutcome(
        succeeded=True, intent="reschedule_task", target_id=slots.task_id,
        detail=f"task {slots.task_id!r} rescheduled",
    )


def list_tasks(store):
    with store.database.connection() as conn:
        rows = conn.execute(
            "SELECT task_id, title, deadline FROM tasks WHERE user_id = ?",
            (USER_ID,),
        ).fetchall()
    return [(r["task_id"], r["title"], r["deadline"]) for r in rows]


def build_context(store):
    return {
        "tasks": [
            {"task_id": tid, "title": title}
            for tid, title, _ in list_tasks(store)
        ],
        "overdue_tasks": [],
    }


def parse_kv(tokens: list[str]) -> dict[str, str]:
    out = {}
    for tok in tokens:
        if "=" not in tok:
            raise ValueError(f"expected key=value, got {tok!r}")
        key, _, value = tok.partition("=")
        out[key] = value
    return out


def main():
    print("=" * 78)
    print("LIVE SESSION -- open item 3: reschedule target authority")
    print("=" * 78)
    print(HELP)

    tmp = tempfile.TemporaryDirectory()
    store = SQLiteStore(f"{tmp.name}/live.db")
    store.ensure_user(USER_ID)
    executor = ActionExecutor(
        store,
        reminder_response_window_minutes=10,
        adaptive_lead_time_enabled=True,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )
    mode = "fixed"

    # Seed two tasks so a bypass has an obvious "wrong task" to demonstrate on.
    t1 = store.save_task(USER_ID, "Team meeting")
    t2 = store.save_task(USER_ID, "Submit thesis")
    print(f"Seeded tasks: 'Team meeting'={t1}  'Submit thesis'={t2}\n")
    print(f"Current mode: {mode}\n")

    while True:
        try:
            raw = input(f"(item3:{mode}) > ").strip()
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
        if cmd == "addtask":
            if not rest:
                print("  usage: addtask <title>")
                continue
            title = " ".join(rest)
            task_id = store.save_task(USER_ID, title)
            print(f"  created task_id={task_id} title={title!r}")
            continue
        if cmd == "list":
            for task_id, title, deadline in list_tasks(store):
                print(f"  {task_id}  {title!r}  deadline={deadline!r}")
            continue
        if cmd == "mode":
            if not rest or rest[0] not in ("fixed", "legacy"):
                print("  usage: mode fixed | mode legacy")
                continue
            mode = rest[0]
            print(f"  mode set to {mode!r}")
            continue
        if cmd == "reschedule":
            try:
                kv = parse_kv(rest)
            except ValueError as exc:
                print(f"  {exc}")
                continue
            if not {"ref", "id", "deadline"} <= kv.keys():
                print("  usage: reschedule ref=<text|-> id=<id|-> deadline=<iso>")
                continue
            slots: dict[str, Any] = {"new_deadline": kv["deadline"]}
            if kv["ref"] != "-":
                slots["task_reference"] = kv["ref"]
            if kv["id"] != "-":
                slots["task_id"] = kv["id"]
            print(f"  slots = {slots}")

            if mode == "fixed":
                outcome = executor.execute({
                    "user_id": USER_ID,
                    "intent": "reschedule_task",
                    "slots": slots,
                    "context": build_context(store),
                })
            else:
                outcome = legacy_execute_reschedule_task(
                    executor, USER_ID, slots, {"context": build_context(store)}
                )
            print(f"  ExecutionOutcome(succeeded={outcome.succeeded}, "
                  f"target_id={outcome.target_id}, error_code={outcome.error_code}, "
                  f"detail={outcome.detail!r})")
            continue

        print(f"  unknown command: {cmd!r} (type `help`)")

    tmp.cleanup()
    print("Session ended.")


if __name__ == "__main__":
    main()
