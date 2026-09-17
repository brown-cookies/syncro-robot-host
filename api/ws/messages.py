"""Phase 14 (WP-105 transport scaffold): WS JSON message contracts, SPEC 7.3.

Scaffold only, per the plan's Phase 14 scope note: these are the message
*shapes* the `/v1/stream` handler will parse and emit. No route exists yet
(`api/ws/stream.py` is still an empty stub), no real clock-sync/session-
registry logic runs anywhere -- this module only gives Phase 14's later
pieces (and Phase 13's already-built `Connection`) typed contracts to
speak in, instead of raw dicts.

Binary messages (`audio_frame`, `tts_audio_frame`, SPEC 7.3) are
deliberately not modeled here: they are raw PCM bytes with no JSON
envelope (avoiding base64 inflation, per SPEC's own rationale), so there
is no schema for pydantic to validate beyond what `audio/resample.py`
already establishes (`BYTES_PER_FRAME` etc.). Only the JSON control
messages get contracts.

`response` (SPEC 8.1) is intentionally not redefined here --
`pipeline.contracts.ResponsePayload` already is that contract; importing
it keeps one definition instead of two drifting copies.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from pipeline.contracts import ResponsePayload


class _Message(BaseModel):
    """Base for this module's WS JSON contracts, mirroring
    `pipeline.contracts._Contract`'s `extra="forbid"` strictness without
    importing that module's private base class across module boundaries."""

    model_config = ConfigDict(extra="forbid")


# Distinct from pipeline.contracts.DegradationReason: SPEC 7.3's error_code
# enum (5 values) and condition_report's condition enum (4 values) are each
# narrower, transport-facing subsets used on the wire, not the full
# 11-value decision-trace vocabulary.
WsErrorCode = Literal[
    "session_collision",
    "malformed_audio",
    "session_timeout",
    "pipeline_failure",
    "queue_overflow",  # SPEC 7.3 amendment, see techdocs/SPEC.md
]
ConditionReportCondition = Literal[
    "mute_engaged",
    "audio_device_unavailable",
    "tts_timeout",
    "playback_error",
]


class StartAudioMessage(_Message):
    """`start_audio` (edge -> host, SPEC 7.3): opens a new in-flight session."""

    type: Literal["start_audio"] = "start_audio"
    session_id: str
    user_id: str
    wake_word_detected_at: int = Field(
        ge=0,
        description="uint64 ms epoch, edge-local clock; required (SPEC 7.3/12).",
    )


class ReadyMessage(_Message):
    """`ready` (host -> edge, SPEC 7.3): acknowledges `start_audio`."""

    type: Literal["ready"] = "ready"
    session_id: str


class EndAudioMessage(_Message):
    """`end_audio` (edge -> host, SPEC 7.3): closes the uplink audio stream.

    `frame_count` is checked against frames actually received on this
    connection for this session; a mismatch is logged, not fatal (SPEC
    7.3/8.2) -- that check is the handler's job (Phase 14 proper), this
    model only carries the field.
    """

    type: Literal["end_audio"] = "end_audio"
    session_id: str
    frame_count: int = Field(ge=0)


class TtsAudioEndMessage(_Message):
    """`tts_audio_end` (host -> edge, SPEC 7.3): closes the downlink audio
    stream for one `response`, mirroring `end_audio` on the uplink."""

    type: Literal["tts_audio_end"] = "tts_audio_end"
    session_id: str
    frame_count: int = Field(ge=0)


class ConditionReportMessage(_Message):
    """`condition_report` (edge -> host, SPEC 7.3).

    Not necessarily tied to an in-flight session -- `session_id` is
    `None` when the condition is reported outside any interaction (e.g.
    mute toggled at idle), per SPEC 7.3's own description of this message.
    """

    type: Literal["condition_report"] = "condition_report"
    session_id: str | None
    condition: ConditionReportCondition
    detected_at: int = Field(
        ge=0, description="uint64 ms epoch, edge-local clock.")


class ErrorMessage(_Message):
    """`error` (host -> edge, SPEC 7.3). Ends the named session on both
    sides without a `response`."""

    type: Literal["error"] = "error"
    session_id: str
    error_code: WsErrorCode
    message: str | None = None


class ClockSyncRequestMessage(_Message):
    """`clock_sync_request` (edge -> host, SPEC 7.4).

    Sent once per connection, immediately after authentication and
    before the first `start_audio`. Not tied to a session_id -- this is
    connection-lifetime state (Phase 13's `Connection.record_clock_sync`),
    not interaction state.
    """

    type: Literal["clock_sync_request"] = "clock_sync_request"
    edge_send_ms: int = Field(ge=0)


class ClockSyncResponseMessage(_Message):
    """`clock_sync_response` (host -> edge, SPEC 7.4).

    Echoes `edge_send_ms` and adds the host's own clock readings at
    receipt and reply, from which the edge (and, per SPEC 7.4, the host
    itself via `Connection.record_clock_sync`) can derive the offset.
    """

    type: Literal["clock_sync_response"] = "clock_sync_response"
    edge_send_ms: int = Field(ge=0)
    host_recv_ms: int = Field(ge=0)
    host_send_ms: int = Field(ge=0)


# Discriminated by `type`, for a handler to parse an incoming frame's raw
# dict without knowing which uplink message it is ahead of time. `response`
# is downlink-only and edge-authored messages are the only ones a host
# handler needs to *parse* (the host constructs its own outgoing messages
# directly), so only uplink types are included.
UplinkMessage = Union[
    StartAudioMessage,
    EndAudioMessage,
    ConditionReportMessage,
    ClockSyncRequestMessage,
]

UPLINK_MESSAGE_TYPES: dict[str, type[UplinkMessage]] = {
    "start_audio": StartAudioMessage,
    "end_audio": EndAudioMessage,
    "condition_report": ConditionReportMessage,
    "clock_sync_request": ClockSyncRequestMessage,
}


class UnknownMessageTypeError(ValueError):
    """Raised by `parse_uplink_message` for a `type` value SPEC 7.3 doesn't
    define as an edge-to-host message."""


def parse_uplink_message(raw: dict) -> UplinkMessage:
    """Parse a raw decoded-JSON dict into its typed uplink message.

    Looks up the model by the message's own `type` field rather than
    trying each model in turn, so an unrecognized `type` fails clearly
    (`UnknownMessageTypeError`) instead of falling through every model's
    validation error in sequence. Whatever pydantic validation error the
    matched model raises (missing/malformed fields) is left to propagate
    as-is -- Phase 14's handler, not this function, decides how a
    malformed uplink message becomes a `malformed_audio`/`error` response.
    """
    message_type = raw.get("type")
    model = UPLINK_MESSAGE_TYPES.get(message_type)  # type: ignore[arg-type]
    if model is None:
        raise UnknownMessageTypeError(
            f"unrecognized uplink message type: {message_type!r}"
        )
    return model.model_validate(raw)


__all__ = [
    "WsErrorCode",
    "ConditionReportCondition",
    "StartAudioMessage",
    "ReadyMessage",
    "EndAudioMessage",
    "TtsAudioEndMessage",
    "ConditionReportMessage",
    "ErrorMessage",
    "ClockSyncRequestMessage",
    "ClockSyncResponseMessage",
    "ResponsePayload",
    "UplinkMessage",
    "UPLINK_MESSAGE_TYPES",
    "UnknownMessageTypeError",
    "parse_uplink_message",
]
