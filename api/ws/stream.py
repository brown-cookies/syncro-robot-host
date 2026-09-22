"""Phase 14 (WP-105 transport): the `/v1/stream` WebSocket route.

Before this module had any content, `api/ws/connection.py` (Phase 13),
`api/ws/messages.py`, and `pipeline/worker.py` (Phase 12) all explicitly
deferred "wiring this together" to here -- see each of their module
docstrings. This is that wiring: the one place that turns SPEC 7.2's
message sequence into calls against those already-built pieces.

Scope note (per the Phase 14 plan): scaffold, not full transport behavior.
What this file *does* do: accept a connection, authenticate it, run the
SPEC 7.4 clock-sync handshake, track one in-flight session per connection
against both `Connection` (local) and `SessionRegistry` (host-wide),
buffer uplink `audio_frame` bytes, submit a completed utterance to the
`InteractionWorker` queue, stream the response and TTS audio back, and
reclaim a session abandoned mid-utterance once it exceeds SPEC 7.4's
inactivity timeout (`StreamDeps.session_timeout_seconds`, `_StreamSession
.run_reaper`) -- closing the "abandoned sessions accumulate for the
process lifetime" gap that rule describes. What it deliberately does *not*
do, left for later, full-behavior work:

- Real device authentication (`default_dev_authenticate` accepts every
  connection) -- SPEC 7.4's device-token check is unimplemented. BL-03
  defers this past the prototype defense (plain WebSocket is sufficient
  on a controlled bench network); this is not scaffold debt to close in
  a hurry.
- Real playback-rate pacing on the downlink -- see `api/ws/downlink.py`.
- Writing `condition_report`'s `degradation_reason` into a decision-trace
  row (SPEC 7.3) -- logged only for now.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from time import monotonic, time
from typing import Callable, Mapping

import numpy as np
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from api.ws.connection import (
    AuthenticationError,
    ClockSyncError,
    Connection,
    DeviceIdentity,
    SessionCollisionError,
)
from api.ws.downlink import DownlinkPacer, ImmediateDownlinkPacer
from api.ws.messages import (
    ClockSyncRequestMessage,
    ClockSyncResponseMessage,
    ConditionReportMessage,
    EndAudioMessage,
    ErrorMessage,
    ReadyMessage,
    ResponsePayload,
    StartAudioMessage,
    TtsAudioEndMessage,
    UnknownMessageTypeError,
    WsErrorCode,
    parse_uplink_message,
)
from api.ws.session_registry import GlobalSessionCollisionError, SessionRegistry
from audio.resample import chunk_100ms
from config import endpoints
from pipeline.interaction import InteractionError, SessionContext
from pipeline.worker import InteractionWorker, WorkerQueueFullError

logger = logging.getLogger(__name__)

router = APIRouter()


def default_dev_authenticate(headers: Mapping[str, str]) -> DeviceIdentity:
    """Placeholder `authenticate` callable for the demo.

    Phase 13's own docstring anticipates exactly this: "the demo can use a
    fixed identity initially; real authentication replaces it later
    without redesigning the handler." This accepts every connection with
    **no real credential check** -- it reads `x-device-id`/`x-user-id`
    request headers if the edge sends them, and falls back to fixed demo
    values otherwise, so a bare connection with no extra headers still
    works during development. Swapping in real device-token validation
    (SPEC 7.4) means replacing this function, not extending it.
    """
    return DeviceIdentity(
        device_id=headers.get("x-device-id", "demo-device"),
        user_id=headers.get("x-user-id", "demo-user"),
    )


@dataclass(frozen=True, slots=True)
class StreamDeps:
    """Everything `stream_endpoint` needs.

    Deliberately a narrower bundle than `composition.bootstrap.HostComponents`:
    the route only ever touches the worker queue, the session registry, and
    a few settings values, never the graph/store/tts objects `HostComponents`
    also carries. Built once by `api/app.py`'s lifespan and attached to
    `app.state`; read-only for the life of the process.

    `session_timeout_seconds` defaults to `config.settings.Settings`'s own
    default (30s) so a `StreamDeps` built without wiring it up still
    matches SPEC 7.4; `api/app.py`'s lifespan passes the real configured
    value explicitly. Tests shorten it to get fast, deterministic reaper
    coverage without a real 30s wait.
    """

    worker: InteractionWorker
    session_registry: SessionRegistry
    audio_sample_rate_hz: int
    authenticate: Callable[[Mapping[str, str]], DeviceIdentity] = default_dev_authenticate
    downlink_pacer: DownlinkPacer = field(default_factory=ImmediateDownlinkPacer)
    session_timeout_seconds: float = 30.0


def get_stream_deps(websocket: WebSocket) -> StreamDeps:
    """FastAPI dependency reading the `StreamDeps` `api/app.py`'s lifespan
    attaches to `app.state`. A `Depends` seam -- rather than importing a
    module-level singleton -- so tests can supply a fake via
    `app.dependency_overrides[get_stream_deps]` instead of monkeypatching.
    """
    return websocket.app.state.stream_deps


def _pcm16_bytes_to_float32(data: bytes) -> np.ndarray:
    """Convert little-endian 16-bit PCM bytes (SPEC 8.2's uplink format)
    into the float32 mono array `WhisperSTTAdapter.transcribe` requires.

    Callers must validate ``len(data) % 2 == 0`` first (SPEC 8.2's
    `malformed_audio` check) -- this does not repeat that check.
    """
    samples = np.frombuffer(data, dtype="<i2")
    return samples.astype(np.float32) / 32768.0


@dataclass
class _InFlightSession:
    """Mutable per-connection state for the one session a connection may
    have in flight at a time (SPEC 7.4).

    Distinct from `pipeline.interaction.SessionContext`: that is the
    runner's immutable input, built fresh from this once `end_audio`
    arrives and the audio buffer is complete.
    """

    session_id: str
    user_id: str
    wake_word_detected_at: int
    started_monotonic: float
    last_activity_monotonic: float
    audio_buffer: bytearray = field(default_factory=bytearray)
    frame_count: int = 0


class _StreamSession:
    """One WebSocket connection's message handling (SPEC 7.2-7.4, 8.2, 8.4, 13).

    A small stateful object rather than local variables inside
    `stream_endpoint` so each uplink message type gets its own reviewable
    method. `connection` (Phase 13) owns auth/clock-offset/local-collision
    state; `self._in_flight` owns the one session's audio buffer, which
    `Connection` deliberately knows nothing about.
    """

    def __init__(self, *, websocket: WebSocket, connection: Connection, deps: StreamDeps) -> None:
        self._ws = websocket
        self._connection = connection
        self._deps = deps
        self._in_flight: _InFlightSession | None = None

    async def _send_json(self, message) -> None:
        await self._ws.send_text(message.model_dump_json())

    async def _send_error(
        self, *, session_id: str, error_code: WsErrorCode, detail: str | None = None
    ) -> None:
        await self._send_json(ErrorMessage(session_id=session_id, error_code=error_code, message=detail))

    def _release_session(self) -> None:
        """End the in-flight session in both the registry and this
        connection's bookkeeping. Safe to call more than once."""
        if self._in_flight is None:
            return
        self._deps.session_registry.end(self._in_flight.session_id)
        try:
            self._connection.end_session(self._in_flight.session_id)
        except ValueError:
            pass  # already cleared on this connection; tolerate a redundant release
        self._in_flight = None

    async def handle_disconnect(self) -> None:
        """Best-effort cleanup when the socket drops mid-session.

        Complements, rather than duplicates, `run_reaper`'s inactivity
        timeout below: this covers the case where the ASGI layer *does*
        tell us the socket closed (a clean disconnect), which is normally
        much faster than waiting out the full inactivity window. The
        reaper is what still catches a hard network drop that never
        delivers a `websocket.disconnect` event at all.
        """
        self._release_session()

    def _seconds_since_activity(self) -> float | None:
        """Seconds since the in-flight session last saw activity, or
        `None` if there is no in-flight session right now."""
        if self._in_flight is None:
            return None
        return monotonic() - self._in_flight.last_activity_monotonic

    async def _reclaim_if_stale(self) -> bool:
        """Reclaim the in-flight session if it has exceeded SPEC 7.4's
        inactivity timeout. Returns whether a session was reclaimed.

        Per SPEC 7.4 this only watches the pre-`end_audio` window -- "no
        `audio_frame` or `end_audio` received" -- not overall interaction
        processing time: `_handle_end_audio` always releases the session
        (`self._in_flight = None`, via `_release_session`) before or as
        soon as it hands the utterance to the worker, on every path
        (success, `InteractionError`, `WorkerQueueFullError`), so this
        check and worker processing never overlap for the same session.
        Total processing time is bounded separately, by
        `INTENT_TIMEOUT_S + REASONING_TIMEOUT_S + NON_LLM_TIMEOUT_MARGIN_S
        < SESSION_TIMEOUT_SECONDS` (`config/settings.py`'s own
        `__post_init__` check) -- there is no second timeout to invent
        here.
        """
        idle = self._seconds_since_activity()
        if idle is None or idle < self._deps.session_timeout_seconds:
            return False
        in_flight = self._in_flight
        assert in_flight is not None  # narrowed by the `idle is None` check above
        await self._send_error(session_id=in_flight.session_id, error_code="session_timeout")
        if self._in_flight is not in_flight:
            # A legitimate end_audio (or error/collision) completed on the
            # main receive loop while the line above was awaiting the
            # socket write -- the only yield point in this method. The
            # stray error message just sent is an unavoidable cost of that
            # race (any timeout mechanism has it: a check and a real
            # message can always land on either side of one instant), but
            # this session_id already belongs to someone else's outcome
            # now -- don't also persist a bogus trace or touch state that
            # isn't ours to release.
            return False
        session = SessionContext(
            session_id=in_flight.session_id,
            user_id=in_flight.user_id,
            started_monotonic=in_flight.started_monotonic,
            wake_word_detected_at=in_flight.wake_word_detected_at,
            clock_offset_ms=self._connection.clock_offset_ms,
        )
        self._deps.worker.runner.persist_session_timeout_trace(session=session)
        self._release_session()
        return True

    async def run_reaper(self) -> None:
        """Background task: periodically reclaim a session abandoned
        without a clean `end_audio`/disconnect (SPEC 7.4's inactivity
        timeout). One instance is started per connection in
        `stream_endpoint` and cancelled in its `finally` block.

        Polls on a fixed interval rather than scheduling one `asyncio`
        timer per session: with at most one in-flight session per
        connection (SPEC 7.4), a plain poll is simpler than juggling timer
        handles across `start_audio`/`end_audio`/`error`, and the ~30s
        target timeout tolerates a coarser poll granularity than this
        while still detecting a test-shortened timeout quickly.
        """
        poll_interval_s = max(0.01, min(5.0, self._deps.session_timeout_seconds / 5))
        try:
            while True:
                await asyncio.sleep(poll_interval_s)
                try:
                    await self._reclaim_if_stale()
                except Exception:
                    # Don't let one bad iteration -- e.g. sending on a
                    # socket that's mid-close -- kill background
                    # monitoring for whatever remains of this connection's
                    # lifetime, or surface as an unexpected exception from
                    # `await reaper_task` in stream_endpoint's cleanup.
                    logger.exception(
                        "session-timeout reaper iteration failed; continuing to poll"
                    )
        except asyncio.CancelledError:
            pass  # normal shutdown path -- stream_endpoint cancels this on disconnect

    async def handle_binary(self, data: bytes) -> None:
        """`audio_frame` (SPEC 8.2): raw uplink PCM, no envelope."""
        if self._in_flight is None:
            logger.warning("dropping audio_frame received outside an active session")
            return
        if len(data) % 2 != 0:
            await self._send_error(
                session_id=self._in_flight.session_id,
                error_code="malformed_audio",
                detail=f"binary frame length {len(data)} is not a multiple of 2",
            )
            self._release_session()
            return
        self._in_flight.audio_buffer.extend(data)
        self._in_flight.frame_count += 1
        self._in_flight.last_activity_monotonic = monotonic()

    async def handle_text(self, raw: str) -> None:
        """Dispatch one JSON control message by its `type` field.

        `ReadyMessage`/`ErrorMessage`/`TtsAudioEndMessage`/
        `ClockSyncResponseMessage` are host->edge only -- `parse_uplink_message`
        already excludes them from `UplinkMessage`, so no branch for them
        is needed here.
        """
        try:
            message = parse_uplink_message(json.loads(raw))
        except (json.JSONDecodeError, UnknownMessageTypeError, ValidationError) as exc:
            logger.warning("dropping unparseable uplink message: %s", exc)
            return

        if isinstance(message, StartAudioMessage):
            await self._handle_start_audio(message)
        elif isinstance(message, EndAudioMessage):
            await self._handle_end_audio(message)
        elif isinstance(message, ClockSyncRequestMessage):
            await self._handle_clock_sync(message)
        elif isinstance(message, ConditionReportMessage):
            self._handle_condition_report(message)

    async def _handle_start_audio(self, message: StartAudioMessage) -> None:
        try:
            self._deps.session_registry.start(message.session_id, self._connection)
        except GlobalSessionCollisionError:
            await self._send_error(session_id=message.session_id, error_code="session_collision")
            return
        try:
            self._connection.start_session(message.session_id)
        except SessionCollisionError:
            # The registry accepted it, but this connection already has a
            # *different* session in flight -- roll the registry entry
            # back so it doesn't leak, then reject like any other
            # collision. The existing session keeps running untouched
            # (SPEC 7.4: "not silently reset").
            self._deps.session_registry.end(message.session_id)
            await self._send_error(session_id=message.session_id, error_code="session_collision")
            return

        now = monotonic()
        self._in_flight = _InFlightSession(
            session_id=message.session_id,
            user_id=message.user_id,
            wake_word_detected_at=message.wake_word_detected_at,
            started_monotonic=now,
            last_activity_monotonic=now,
        )
        await self._send_json(ReadyMessage(session_id=message.session_id))

    async def _handle_clock_sync(self, message: ClockSyncRequestMessage) -> None:
        host_recv_ms = int(time() * 1000)
        host_send_ms = int(time() * 1000)
        try:
            self._connection.record_clock_sync(
                edge_send_ms=message.edge_send_ms,
                host_recv_ms=host_recv_ms,
                host_send_ms=host_send_ms,
            )
        except ClockSyncError as exc:
            # SPEC 7.4 doesn't define a wire error for a repeated
            # handshake -- most likely a well-behaved edge retrying, not a
            # protocol violation, so this is logged and otherwise ignored
            # rather than closing the connection over it.
            logger.warning("ignoring repeated clock_sync_request: %s", exc)
            return
        await self._send_json(
            ClockSyncResponseMessage(
                edge_send_ms=message.edge_send_ms,
                host_recv_ms=host_recv_ms,
                host_send_ms=host_send_ms,
            )
        )

    def _handle_condition_report(self, message: ConditionReportMessage) -> None:
        """Logged only for now.

        SPEC 7.3 says the host writes `degradation_reason` onto the
        decision-trace row for `message.session_id` on receipt; doing that
        for real means reaching into storage outside
        `InteractionRunner`'s own write path (F1), which is later,
        full-behavior work, not this scaffold's job.
        """
        logger.info(
            "condition_report received: condition=%s session_id=%s detected_at=%s",
            message.condition,
            message.session_id,
            message.detected_at,
        )

    async def _handle_end_audio(self, message: EndAudioMessage) -> None:
        in_flight = self._in_flight
        if in_flight is None or message.session_id != in_flight.session_id:
            logger.warning(
                "end_audio for session_id=%r does not match the in-flight session (%r); ignoring",
                message.session_id,
                in_flight.session_id if in_flight else None,
            )
            return
        if message.frame_count != in_flight.frame_count:
            # SPEC 8.2/7.3: a mismatch is a logged anomaly, never fatal --
            # TCP already guarantees delivery on a live connection, so this
            # indicates an edge-side counting bug, not lost audio.
            logger.warning(
                "end_audio frame_count mismatch for session_id=%r: edge reported %d, host received %d",
                message.session_id,
                message.frame_count,
                in_flight.frame_count,
            )

        audio = _pcm16_bytes_to_float32(bytes(in_flight.audio_buffer))
        session = SessionContext(
            session_id=in_flight.session_id,
            user_id=in_flight.user_id,
            started_monotonic=in_flight.started_monotonic,
            wake_word_detected_at=in_flight.wake_word_detected_at,
            clock_offset_ms=self._connection.clock_offset_ms,
        )

        try:
            future = self._deps.worker.submit(
                session=session, audio=audio, sample_rate=self._deps.audio_sample_rate_hz
            )
        except WorkerQueueFullError:
            await self._send_error(session_id=session.session_id, error_code="queue_overflow")
            self._release_session()
            return

        try:
            result = await asyncio.wrap_future(future)
        except InteractionError as exc:
            await self._send_error(
                session_id=session.session_id, error_code=exc.wire_code, detail=str(exc)
            )
            self._release_session()
            return

        payload = ResponsePayload.model_validate(result.response_payload)
        await self._send_json(payload)

        chunks = chunk_100ms(result.tts_audio)
        await self._deps.downlink_pacer.send(chunks, self._ws.send_bytes)
        await self._send_json(
            TtsAudioEndMessage(session_id=session.session_id, frame_count=len(chunks))
        )

        self._release_session()


@router.websocket(endpoints.WS_STREAM)
async def stream_endpoint(websocket: WebSocket, deps: StreamDeps = Depends(get_stream_deps)) -> None:
    """`/v1/stream` (SPEC 7.1-7.4): one persistent connection per edge unit.

    See this module's docstring for exactly what is and is not implemented
    at this phase.
    """
    await websocket.accept()
    connection = Connection(authenticate=deps.authenticate)
    try:
        connection.authenticate(dict(websocket.headers))
    except AuthenticationError as exc:
        logger.warning("rejecting unauthenticated WS connection: %s", exc)
        await websocket.close(code=4401, reason="authentication failed")
        return

    session = _StreamSession(websocket=websocket, connection=connection, deps=deps)
    reaper_task = asyncio.create_task(session.run_reaper())
    try:
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            frame_bytes = frame.get("bytes")
            if frame_bytes is not None:
                await session.handle_binary(frame_bytes)
                continue
            frame_text = frame.get("text")
            if frame_text is not None:
                await session.handle_text(frame_text)
    except WebSocketDisconnect:
        pass
    finally:
        reaper_task.cancel()
        await reaper_task
        await session.handle_disconnect()


__all__ = ["router", "StreamDeps", "get_stream_deps", "default_dev_authenticate"]
