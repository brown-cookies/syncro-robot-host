"""Regression tests for the Phase 14 session registry.

`api/ws/connection.py`'s `Connection.start_session` already covers the
per-connection collision case (see `tests/unit/api/test_connection.py`);
these tests cover only what `Connection` cannot see by itself: a
`session_id` colliding across two *different* connections.
"""

from __future__ import annotations

from api.ws.session_registry import GlobalSessionCollisionError, SessionRegistry


def test_start_registers_a_new_session():
    registry: SessionRegistry[str] = SessionRegistry()

    registry.start("s1", "connection-a")

    assert registry.owner("s1") == "connection-a"
    assert registry.in_flight_count == 1


def test_start_rejects_a_session_id_already_owned_by_another_connection():
    registry: SessionRegistry[str] = SessionRegistry()
    registry.start("s1", "connection-a")

    try:
        registry.start("s1", "connection-b")
        assert False, "expected GlobalSessionCollisionError"
    except GlobalSessionCollisionError:
        pass

    # The original owner is untouched by the rejected second start.
    assert registry.owner("s1") == "connection-a"


def test_start_rejects_the_same_session_id_from_the_same_connection_too():
    """A caller that wants "already mine" to be a no-op must check
    `owner()` itself -- silently accepting a second `start` from the same
    connection would hide a real double-registration bug (see the
    docstring on `SessionRegistry.start`)."""
    registry: SessionRegistry[str] = SessionRegistry()
    registry.start("s1", "connection-a")

    try:
        registry.start("s1", "connection-a")
        assert False, "expected GlobalSessionCollisionError"
    except GlobalSessionCollisionError:
        pass


def test_end_releases_a_session_so_it_can_be_reused():
    registry: SessionRegistry[str] = SessionRegistry()
    registry.start("s1", "connection-a")

    registry.end("s1")

    assert registry.owner("s1") is None
    assert registry.in_flight_count == 0
    registry.start("s1", "connection-b")  # does not raise
    assert registry.owner("s1") == "connection-b"


def test_end_on_an_unregistered_session_id_is_not_an_error():
    registry: SessionRegistry[str] = SessionRegistry()

    registry.end("never-started")  # must not raise

    assert registry.in_flight_count == 0


def test_owner_returns_none_for_an_unknown_session_id():
    registry: SessionRegistry[str] = SessionRegistry()

    assert registry.owner("unknown") is None
