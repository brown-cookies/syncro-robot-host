import pytest

from api.ws.connection import (
    AuthenticationError,
    ClockSyncError,
    Connection,
    DeviceIdentity,
    SessionCollisionError,
)


def _fixed_identity_authenticator(headers):
    """A fake `authenticate` callable standing in for real device_token
    validation (Phase 13's stated demo behavior: fixed identity)."""
    if headers.get("Authorization") != "Bearer valid-token":
        raise AuthenticationError("missing or invalid device_token")
    return DeviceIdentity(device_id="edge-01", user_id="wp103-demo-user")


def test_connection_starts_unauthenticated() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    assert connection.is_authenticated is False


def test_device_id_raises_before_authentication() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    with pytest.raises(RuntimeError):
        connection.device_id


def test_authenticate_stores_identity_on_success() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    identity = connection.authenticate({"Authorization": "Bearer valid-token"})
    assert identity == DeviceIdentity(
        device_id="edge-01", user_id="wp103-demo-user")
    assert connection.is_authenticated is True
    assert connection.device_id == "edge-01"
    assert connection.user_id == "wp103-demo-user"


def test_authenticate_propagates_failure_without_storing_identity() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    with pytest.raises(AuthenticationError):
        connection.authenticate({"Authorization": "Bearer wrong-token"})
    assert connection.is_authenticated is False


def test_authenticate_rejects_a_second_call_after_success() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    connection.authenticate({"Authorization": "Bearer valid-token"})
    with pytest.raises(AuthenticationError):
        connection.authenticate({"Authorization": "Bearer valid-token"})
    # the original identity is untouched by the rejected second call
    assert connection.device_id == "edge-01"


def test_authenticate_allows_retry_after_a_failed_attempt() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    with pytest.raises(AuthenticationError):
        connection.authenticate({"Authorization": "Bearer wrong-token"})
    # a failed attempt leaves the connection in NEW, not a rejected state
    identity = connection.authenticate({"Authorization": "Bearer valid-token"})
    assert identity == DeviceIdentity(
        device_id="edge-01", user_id="wp103-demo-user")


def test_clock_offset_is_none_before_sync() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    assert connection.clock_offset_ms is None


def test_record_clock_sync_computes_spec_7_4_midpoint_offset() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    # edge sends at 1000, host receives at 1050, host replies at 1060:
    # offset = ((1050 - 1000) + (1060 - 1000)) / 2 = (50 + 60) / 2 = 55
    offset = connection.record_clock_sync(
        edge_send_ms=1000, host_recv_ms=1050, host_send_ms=1060
    )
    assert offset == 55.0
    assert connection.clock_offset_ms == 55.0


def test_record_clock_sync_handles_negative_offset() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    offset = connection.record_clock_sync(
        edge_send_ms=2000, host_recv_ms=1950, host_send_ms=1960
    )
    assert offset == -45.0


def test_record_clock_sync_rejects_a_second_call() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    connection.record_clock_sync(
        edge_send_ms=1000, host_recv_ms=1050, host_send_ms=1060
    )
    with pytest.raises(ClockSyncError):
        connection.record_clock_sync(
            edge_send_ms=2000, host_recv_ms=1950, host_send_ms=1960
        )
    # the original offset is untouched by the rejected second call
    assert connection.clock_offset_ms == 55.0


def test_start_session_marks_session_in_flight() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    connection.start_session("session-1")
    assert connection.in_flight_session_id == "session-1"


def test_start_session_raises_on_collision() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    connection.start_session("session-1")
    with pytest.raises(SessionCollisionError):
        connection.start_session("session-2")
    # the original session is untouched by the rejected collision
    assert connection.in_flight_session_id == "session-1"


def test_end_session_clears_in_flight_state() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    connection.start_session("session-1")
    connection.end_session("session-1")
    assert connection.in_flight_session_id is None


def test_end_session_allows_a_new_session_after_the_old_one_ends() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    connection.start_session("session-1")
    connection.end_session("session-1")
    connection.start_session("session-2")
    assert connection.in_flight_session_id == "session-2"


def test_end_session_rejects_a_session_id_that_is_not_in_flight() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    connection.start_session("session-1")
    with pytest.raises(ValueError):
        connection.end_session("session-wrong")
    # the actually in-flight session is untouched by the bad call
    assert connection.in_flight_session_id == "session-1"


def test_end_session_rejects_ending_when_nothing_is_in_flight() -> None:
    connection = Connection(authenticate=_fixed_identity_authenticator)
    with pytest.raises(ValueError):
        connection.end_session("session-1")
