"""LIVE interactive session: open item 2 -- newer utterance wins.

You submit jobs yourself, in real time, into the REAL
`pipeline.worker.InteractionWorker` (the actual single-thread, FIFO,
per-user-sequenced worker the host uses). Each job you submit can carry its
own artificial processing delay, so you can reproduce the race described in
the open item yourself: submit a "slow" older instruction, then quickly
submit a "fast" newer one, and watch that the newer one still wins because
of submission order, not completion order.

There is no scripted transcript here -- `status` reflects whatever you've
actually submitted, in the order the worker actually processed it.

Run:
    python -m scripts.live_open_item_2_utterance_ordering

Commands:
    submit <label> <delay_s>   submit a job; it "completes" after delay_s
                                 seconds and sets label as the current final
                                 action (e.g. `submit snoozed 2`)
    status                     show submission order, completion order, and
                                 the current final_action
    wait <seconds>             block for N seconds (handy while jobs finish)
    quit                       stop the worker and exit
"""

from __future__ import annotations

import shlex
import threading
import time

from pipeline.interaction import SessionContext
from pipeline.worker import InteractionWorker

USER_ID = "u1"
HELP = __doc__.split("Commands")[1]


class LiveState:
    def __init__(self):
        self.lock = threading.Lock()
        self.submitted: list[tuple[int, str, float, float]] = []  # (seq, label, delay, submitted_at)
        self.completed: list[tuple[int, str, float]] = []          # (seq, label, completed_at)
        self.final_action: str | None = None
        self._next_seq = 0

    def record_submit(self, label: str, delay: float) -> int:
        with self.lock:
            seq = self._next_seq
            self._next_seq += 1
            self.submitted.append((seq, label, delay, time.monotonic()))
            return seq

    def record_complete(self, seq: int, label: str) -> None:
        with self.lock:
            self.completed.append((seq, label, time.monotonic()))
            self.final_action = label
            print(f"\n  [worker] finished seq={seq} label={label!r} "
                  f"-> final_action is now {label!r}")


class LiveRunner:
    """Duck-types InteractionRunner.run for the real InteractionWorker,
    without needing STT/TTS/graph machinery."""

    def __init__(self, state: LiveState):
        self._state = state

    def run(self, *, session, audio, sample_rate):
        seq = int(session.session_id.split(":")[0])
        label = session.session_id.split(":", 1)[1]
        delay = float(audio[0])
        print(f"  [worker] started  seq={seq} label={label!r} (will take {delay}s)")
        time.sleep(delay)
        self._state.record_complete(seq, label)
        return None


def main():
    print("=" * 78)
    print("LIVE SESSION -- open item 2: newer utterance wins")
    print("=" * 78)
    print(HELP)
    print("Try reproducing the open item's race yourself, e.g.:")
    print("    submit snoozed 3      (older, slow to process)")
    print("    submit dismissed 0.2  (newer, fast to process)")
    print("    status                (watch 'dismissed' win once both finish,")
    print("                           even though 'snoozed' is still running)")
    print()

    state = LiveState()
    runner = LiveRunner(state)
    worker = InteractionWorker(runner=runner, maxsize=50)
    worker.start()

    while True:
        try:
            raw = input("(item2) > ").strip()
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
        if cmd == "submit":
            if len(rest) != 2:
                print("  usage: submit <label> <delay_s>")
                continue
            label, delay_str = rest
            try:
                delay = float(delay_str)
            except ValueError:
                print("  delay_s must be a number, e.g. 0.5")
                continue
            seq = state.record_submit(label, delay)
            session = SessionContext(
                session_id=f"{seq}:{label}",
                user_id=USER_ID,
                started_monotonic=time.monotonic(),
            )
            worker.submit(session=session, audio=[delay], sample_rate=16_000)
            print(f"  submitted seq={seq} label={label!r} delay={delay}s "
                  f"(queue_depth={worker.queue_depth})")
            continue
        if cmd == "wait":
            if len(rest) != 1:
                print("  usage: wait <seconds>")
                continue
            try:
                seconds = float(rest[0])
            except ValueError:
                print("  seconds must be a number")
                continue
            time.sleep(seconds)
            continue
        if cmd == "status":
            with state.lock:
                print("  submitted (in submission order):")
                for seq, label, delay, at in state.submitted:
                    done = any(c[0] == seq for c in state.completed)
                    print(f"    seq={seq} label={label!r} delay={delay}s "
                          f"{'[done]' if done else '[pending/running]'}")
                print("  completed (in completion order):")
                for seq, label, at in state.completed:
                    print(f"    seq={seq} label={label!r}")
                print(f"  final_action = {state.final_action!r}")
            continue

        print(f"  unknown command: {cmd!r} (type `help`)")

    print("stopping worker (waits for anything already queued)...")
    worker.stop(timeout=30)
    print("Session ended.")


if __name__ == "__main__":
    main()
