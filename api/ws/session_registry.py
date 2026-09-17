"""Phase 14 (WP-105 transport scaffold): the host-wide session registry.

`api/ws/connection.py` (Phase 13, S6) already enforces "one in-flight
session_id at a time" *per connection* -- `Connection.start_session` only
knows about itself. SPEC 7.4 asks for a stronger guarantee: one
`session_id` maps to exactly one in-flight utterance across the **whole
host**, so a collision must also be caught if two different connections
(e.g. a reconnecting edge that never sent `end_audio` on the old socket)
both try to start the same `session_id`. `connection.py`'s own docstring
names this gap explicitly and defers it here.

Scope note (per the Phase 14 plan): this is the registry's *shape* --
enough bookkeeping to answer "is this session_id already in flight
somewhere on this host" and reject or release it. It is deliberately
**not** the full SPEC 7.4 session-expiry contract: reclaiming a session
whose connection drops without `end_audio`/`error`, or whose 30s
inactivity timeout (`session_timeout_seconds`) fires, is real behavior
that a later phase must add (SPEC 7.4's "session expiry" bullet). Nothing
here should be mistaken for that.
"""

from __future__ import annotations

import threading
from typing import Generic, TypeVar

# Deliberately generic over the connection-identifying value rather than
# importing `api.ws.connection.Connection` -- the registry only needs
# *something* to say "which connection owns this session_id" (used for a
# collision message and, later, for locating the right connection to push
# an out-of-band `error` to). Tests can register plain sentinel objects
# without constructing a real `Connection`.
_ConnectionT = TypeVar("_ConnectionT")


class GlobalSessionCollisionError(RuntimeError):
    """Raised when `session_id` is already in flight on *some* connection.

    Distinct from `api.ws.connection.SessionCollisionError`, which only
    catches a collision on one connection. This is the host-wide check
    SPEC 7.4 asks for; `stream.py` is expected to check this registry
    before (or alongside) the per-connection check.
    """


class SessionRegistry(Generic[_ConnectionT]):
    """Tracks which connection owns each in-flight `session_id`, host-wide.

    A plain dict guarded by a lock is enough for the single-process
    deployment this scaffold targets (one Uvicorn worker, per the demo
    plan) -- there is no cross-process state to synchronize. The lock
    exists mainly so a future multi-threaded caller (e.g. the session-
    timeout reaper this scope note says is still missing) can't race the
    async handlers' `start`/`end` calls; it is not read as a promise that
    this class works across multiple host processes.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _ConnectionT] = {}
        self._lock = threading.Lock()

    def start(self, session_id: str, connection: _ConnectionT) -> None:
        """Register `session_id` as in flight, owned by `connection`.

        Raises `GlobalSessionCollisionError` if `session_id` is already
        registered to any connection (including this same one -- a caller
        that wants "already mine" to be a no-op must check
        `owner(session_id)` itself; silently accepting a second `start`
        here would hide a real bug in the caller's own bookkeeping).
        """
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                raise GlobalSessionCollisionError(
                    f"session_id {session_id!r} is already in flight on "
                    f"another connection; rejecting start_audio"
                )
            self._sessions[session_id] = connection

    def end(self, session_id: str) -> None:
        """Release `session_id` so a future `start_audio` may reuse it.

        Not an error to call for a `session_id` that isn't registered --
        callers may reach this from an exception-handling path where it's
        already unclear whether registration succeeded, and treating a
        redundant release as fatal would only complicate that cleanup
        code for no real safety benefit.
        """
        with self._lock:
            self._sessions.pop(session_id, None)

    def owner(self, session_id: str) -> _ConnectionT | None:
        """Return the connection currently holding `session_id`, if any."""
        with self._lock:
            return self._sessions.get(session_id)

    @property
    def in_flight_count(self) -> int:
        """Number of sessions currently registered (observability only)."""
        with self._lock:
            return len(self._sessions)


__all__ = ["SessionRegistry", "GlobalSessionCollisionError"]
