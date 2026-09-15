"""Phase 13 (finding S6): the seam for future device authentication and
latency clock-offset synchronization.

This module does not touch a real WebSocket -- `api/ws/stream.py`'s route
shape is Phase 14 scope. This phase only builds the object that handler
will hold: identity (`device_id`/`user_id`) resolved by an injected
`authenticate(headers)` callable, the SPEC 7.4 clock-offset handshake, and
enough per-connection session state to enforce "one in-flight session_id
at a time" locally. The demo can construct a `Connection` with a fixed
`authenticate` callable; swapping in real device-token validation later
is a drop-in replacement for that callable, not a redesign of this class
or whatever holds it.

Session *registry* state spanning multiple connections (SPEC 7.4's
session_id collision check across the whole host, not just one
connection) is Phase 14's "session registry stub" -- out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


class AuthenticationError(RuntimeError):
    """Raised by an injected `authenticate` callable when a connection's
    credentials are missing or invalid.

    Per SPEC 7.4: on failure the host refuses the WebSocket upgrade and
    logs `connect_failed` -- that handling belongs to Phase 14's transport
    layer, which is expected to catch this exception; this module only
    defines the stable type it's expected to raise.
    """


class SessionCollisionError(RuntimeError):
    """Raised when a session_id is started while another is already in
    flight on this connection.

    Per SPEC 7.4: a `start_audio` for a session_id already in flight is
    rejected outright -- the existing session keeps running, it is not
    silently reset.
    """


class ClockSyncError(RuntimeError):
    """Raised when `record_clock_sync` is called on a connection that
    already has a stored `clock_offset_ms`.

    Per SPEC 7.4, the clock-offset handshake happens once per connection
    and the result is stored for that connection's whole lifetime -- a
    second call is a handler bug (e.g. a retried handshake), not a valid
    re-sync, and must not silently overwrite the stored offset.
    """


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """What a successful `authenticate(headers)` call resolves to."""

    device_id: str
    user_id: str


class Connection:
    """One authenticated WebSocket connection's lifetime state.

    Constructed unauthenticated: `device_id`/`user_id` are unavailable
    until `authenticate` is called once with the connection's upgrade
    headers (SPEC 7.4 -- authentication happens once, at connection
    establishment, not per session). This is an enforced state machine,
    not just a documented convention:

        NEW -> authenticate() succeeds  -> AUTHENTICATED
        NEW -> authenticate() fails     -> NEW (retry allowed)
        AUTHENTICATED -> authenticate() -> rejected (AuthenticationError)

    `clock_offset_ms` stays `None` until `record_clock_sync` is called
    once, immediately after authentication. Until then,
    `InteractionRunner._compute_latency`'s `host_observed_only` fallback
    applies for every session run on this connection (SPEC 7.4/12). A
    second `record_clock_sync` call is likewise rejected (`ClockSyncError`)
    rather than silently replacing the stored offset -- enforcing the
    "computed once, for the connection's lifetime" contract in code
    instead of leaving it to Phase 14's handler to remember.

    These two steps stay separate methods on purpose, matching the wire
    protocol's own ordering (WebSocket upgrade -> authentication ->
    clock_sync_request/response -> first start_audio, SPEC 7.4):
    `authenticate` does not call `record_clock_sync` itself. Phase 14's
    handler is expected to call them as two distinct steps in response to
    two distinct wire events.

    `authenticate` is injected -- matching the pattern already used for
    `InteractionRunner`'s `resampler`/`clock` -- so tests can supply a
    fixed identity without a real device_token, and so swapping in real
    token validation later doesn't require changing this class.
    """

    def __init__(
        self, *, authenticate: Callable[[Mapping[str, str]], DeviceIdentity]
    ) -> None:
        self._authenticate = authenticate
        self._identity: DeviceIdentity | None = None
        self.clock_offset_ms: float | None = None
        self._in_flight_session_id: str | None = None

    @property
    def is_authenticated(self) -> bool:
        """Whether `authenticate` has completed successfully on this connection."""
        return self._identity is not None

    @property
    def device_id(self) -> str:
        return self._require_identity().device_id

    @property
    def user_id(self) -> str:
        return self._require_identity().user_id

    @property
    def in_flight_session_id(self) -> str | None:
        """The session_id currently in flight on this connection, if any."""
        return self._in_flight_session_id

    def authenticate(self, headers: Mapping[str, str]) -> DeviceIdentity:
        """Resolve and store this connection's identity from `headers`.

        Raises `AuthenticationError` if this connection is already
        authenticated -- SPEC 7.4 treats authentication as a one-time
        step at connection establishment, so a second call (even with
        identical, valid headers) is rejected rather than silently
        replacing the stored identity; a connection is not meant to be
        re-authenticated mid-lifetime.

        On a first attempt, delegates to the injected `authenticate`
        callable and propagates whatever it raises on failure (expected
        to be `AuthenticationError`) without storing a partial or failed
        identity -- the connection stays in the NEW state and a retry is
        allowed.
        """
        if self._identity is not None:
            raise AuthenticationError(
                "connection is already authenticated as "
                f"device_id={self._identity.device_id!r}; "
                "authenticate() cannot be called a second time"
            )
        identity = self._authenticate(headers)
        self._identity = identity
        return identity

    def record_clock_sync(
        self, *, edge_send_ms: int, host_recv_ms: int, host_send_ms: int
    ) -> float:
        """Compute and store this connection's clock offset (SPEC 7.4).

        ``offset = ((host_recv_ms - edge_send_ms) + (host_send_ms - edge_send_ms)) / 2``

        The standard midpoint estimate: it cancels one-way transit time
        to first order. Called once, right after authentication and
        before the first `start_audio` on this connection; the result is
        stored for the connection's whole lifetime.

        Raises `ClockSyncError` if an offset is already stored -- a
        second call would otherwise silently replace a value SPEC 7.4
        says is fixed for the connection's lifetime, relying on Phase
        14's handler to remember never to call this twice instead of the
        contract enforcing it here.
        """
        if self.clock_offset_ms is not None:
            raise ClockSyncError(
                f"clock sync already recorded for this connection "
                f"(clock_offset_ms={self.clock_offset_ms}); "
                "record_clock_sync() cannot be called a second time"
            )
        offset = (
            (host_recv_ms - edge_send_ms) + (host_send_ms - edge_send_ms)
        ) / 2
        self.clock_offset_ms = float(offset)
        return self.clock_offset_ms

    def start_session(self, session_id: str) -> None:
        """Mark `session_id` as in flight on this connection.

        Raises `SessionCollisionError` if another session is already in
        flight (SPEC 7.4).
        """
        if self._in_flight_session_id is not None:
            raise SessionCollisionError(
                f"session {self._in_flight_session_id!r} is already in flight "
                f"on this connection; rejecting start_audio for {session_id!r}"
            )
        self._in_flight_session_id = session_id

    def end_session(self, session_id: str) -> None:
        """Mark `session_id` as no longer in flight on this connection.

        Raises `ValueError` if `session_id` isn't the one currently in
        flight -- a caller trying to end a session that was never
        started here indicates a handler bug (Phase 14 hasn't been
        built yet), not a valid state transition.
        """
        if self._in_flight_session_id != session_id:
            raise ValueError(
                f"cannot end session {session_id!r}: currently in-flight "
                f"session is {self._in_flight_session_id!r}"
            )
        self._in_flight_session_id = None

    def _require_identity(self) -> DeviceIdentity:
        if self._identity is None:
            raise RuntimeError(
                "Connection is not authenticated yet; call authenticate(headers) first"
            )
        return self._identity
