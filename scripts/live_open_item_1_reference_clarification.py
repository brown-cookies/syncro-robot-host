"""LIVE interactive session: open item 1 -- reminder reference clarification.

This is not a scripted transcript. It's a REPL: you type commands, and each
one runs straight through the REAL pipeline code
(`pipeline.nodes.reference_resolution.make_reference_resolution_node` and
`pipeline.executor.ActionExecutor`) against a real (temp) SQLite store. You
can seed as many pending reminders as you want and drive the clarification
back-and-forth yourself.

Run:
    python -m scripts.live_open_item_1_reference_clarification

Commands (type `help` in-session for this list too):
    seed <title>                 seed a new pending reminder for u1
    list                         show current pending reminders
    say snooze <minutes> <text>  turn: intent=snooze_reminder, your transcript
    say dismiss <text>           turn: intent=dismiss_reminder, your transcript
    reset                        clear any in-flight clarification
    quit                         exit
"""

from __future__ import annotations

import shlex
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pipeline.executor import ActionExecutor
from pipeline.nodes.reference_resolution import make_reference_resolution_node
from pipeline.reference_resolution import ReferenceClarificationStore
from storage.sqlite_store import SQLiteStore

USER_ID = "u1"
HELP = __doc__.split("Commands")[1]


def seed_pending_reminder(store, *, minutes_ago, task_title):
    task_id = store.save_task(USER_ID, task_title)
    trace_id = str(uuid4())
    timestamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    with store.database.connection() as conn:
        conn.execute(
            """
            INSERT INTO decision_trace(
                trace_id, session_id, user_id, timestamp, intent,
                intent_confidence, retrieved_context_ids, affect_level,
                deadline_proximity, policy_rule, action_taken, lead_time_min,
                reminder_outcome, degradation_reason, network_event,
                latency_ms, latency_basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id, "live-session", USER_ID, timestamp.isoformat(),
                "request_summary", 0.95, f'["{task_id}"]', "Moderate",
                "not_imminent", "R2", "defer", 15.0, "pending", None, None,
                1.0, "host_observed_only",
            ),
        )
    return trace_id


def list_pending(store):
    with store.database.connection() as conn:
        rows = conn.execute(
            """
            SELECT dt.trace_id, t.title, dt.timestamp
              FROM decision_trace dt
              JOIN tasks t ON t.task_id IN (
                  SELECT value FROM json_each(dt.retrieved_context_ids)
              )
             WHERE dt.user_id = ? AND dt.reminder_outcome = 'pending'
             ORDER BY dt.timestamp DESC
            """,
            (USER_ID,),
        ).fetchall()
    return [(row["trace_id"], row["title"], row["timestamp"]) for row in rows]


def main():
    print("=" * 78)
    print("LIVE SESSION -- open item 1: reminder reference clarification")
    print("=" * 78)
    print(HELP)

    tmp = tempfile.TemporaryDirectory()
    store = SQLiteStore(f"{tmp.name}/live.db")
    store.ensure_user(USER_ID)
    clarification_store = ReferenceClarificationStore()
    node = make_reference_resolution_node(
        store, clarification_store, reminder_response_window_minutes=120
    )
    executor = ActionExecutor(
        store,
        reminder_response_window_minutes=120,
        adaptive_lead_time_enabled=True,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )

    # Seed two ambiguous reminders to start, like the open item's example.
    seed_pending_reminder(store, minutes_ago=8, task_title="Submit thesis")
    seed_pending_reminder(store, minutes_ago=1, task_title="Team meeting")
    print("Seeded 2 pending reminders to start: 'Submit thesis', 'Team meeting'.\n")

    while True:
        try:
            raw = input("(item1) > ").strip()
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
        if cmd == "reset":
            clarification_store.clear(USER_ID)
            print("  cleared any in-flight clarification for u1.")
            continue
        if cmd == "seed":
            if not rest:
                print("  usage: seed <title>")
                continue
            title = " ".join(rest)
            seed_pending_reminder(store, minutes_ago=0.1, task_title=title)
            print(f"  seeded pending reminder for {title!r}.")
            continue
        if cmd == "list":
            pending = list_pending(store)
            if not pending:
                print("  (no pending reminders)")
            for trace_id, title, timestamp in pending:
                print(f"  {trace_id}  {title!r}  dispatched {timestamp}")
            continue
        if cmd == "say":
            if len(rest) < 1 or rest[0] not in ("snooze", "dismiss"):
                print("  usage: say snooze <minutes> <text>  |  say dismiss <text>")
                continue
            intent_word = rest.pop(0)
            intent = "snooze_reminder" if intent_word == "snooze" else "dismiss_reminder"
            slots = {}
            if intent == "snooze_reminder":
                if not rest or not rest[0].isdigit():
                    print("  usage: say snooze <minutes> <text>")
                    continue
                slots["snooze_minutes"] = int(rest.pop(0))
            transcript = " ".join(rest) if rest else ""
            print(f'  transcript: "{transcript}"')

            turn_state = {
                "user_id": USER_ID,
                "intent": intent,
                "transcript": transcript,
                "slots": slots,
            }
            result = node(turn_state)
            status = result.get("reference_resolution_status")
            print(f"  reference_resolution_status = {status!r}")

            if status == "needs_clarification":
                print(f'  ASSISTANT ASKS: "{result["final_response"]}"')
                print("  (type your answer with another `say` command, e.g. "
                      "`say snooze 10 the thesis one`)")
                continue
            if status == "not_found":
                print("  -> no pending reminder found; nothing executed.")
                continue

            # resolved -- run the real executor on the resolved slots
            exec_state = {
                "user_id": USER_ID,
                "intent": intent,
                "slots": result["slots"],
                "reference_resolution_status": "resolved",
            }
            outcome = executor.execute(exec_state)
            print(f"  reference_trace_id = {result['slots']['reference_trace_id']}")
            print(f"  ExecutionOutcome(succeeded={outcome.succeeded}, "
                  f"target_id={outcome.target_id}, error_code={outcome.error_code}, "
                  f"detail={outcome.detail!r})")
            continue

        print(f"  unknown command: {cmd!r} (type `help`)")

    tmp.cleanup()
    print("Session ended.")


if __name__ == "__main__":
    main()
