import pytest
from pydantic import ValidationError

from api.ws.messages import (
    UPLINK_MESSAGE_TYPES,
    ClockSyncRequestMessage,
    ClockSyncResponseMessage,
    ConditionReportMessage,
    EndAudioMessage,
    ErrorMessage,
    ReadyMessage,
    StartAudioMessage,
    TtsAudioEndMessage,
    UnknownMessageTypeError,
    parse_uplink_message,
)
from pipeline.contracts import ResponsePayload


def test_start_audio_round_trips_the_spec_7_3_fields() -> None:
    message = StartAudioMessage(
        session_id="session-1", user_id="user-1", wake_word_detected_at=1_700_000_000_000
    )
    assert message.model_dump() == {
        "type": "start_audio",
        "session_id": "session-1",
        "user_id": "user-1",
        "wake_word_detected_at": 1_700_000_000_000,
    }


def test_start_audio_requires_wake_word_detected_at() -> None:
    with pytest.raises(ValidationError):
        StartAudioMessage(session_id="session-1", user_id="user-1")


def test_start_audio_rejects_a_negative_timestamp() -> None:
    with pytest.raises(ValidationError):
        StartAudioMessage(session_id="session-1",
                          user_id="user-1", wake_word_detected_at=-1)


def test_start_audio_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        StartAudioMessage.model_validate(
            {
                "session_id": "session-1",
                "user_id": "user-1",
                "wake_word_detected_at": 1,
                "unexpected_field": "nope",
            }
        )


def test_ready_carries_only_session_id() -> None:
    message = ReadyMessage(session_id="session-1")
    assert message.model_dump() == {"type": "ready", "session_id": "session-1"}


def test_end_audio_requires_a_nonnegative_frame_count() -> None:
    message = EndAudioMessage(session_id="session-1", frame_count=42)
    assert message.frame_count == 42
    with pytest.raises(ValidationError):
        EndAudioMessage(session_id="session-1", frame_count=-1)


def test_tts_audio_end_mirrors_end_audio_shape() -> None:
    message = TtsAudioEndMessage(session_id="session-1", frame_count=7)
    assert message.model_dump() == {
        "type": "tts_audio_end",
        "session_id": "session-1",
        "frame_count": 7,
    }


def test_condition_report_allows_a_null_session_id() -> None:
    message = ConditionReportMessage(
        session_id=None, condition="mute_engaged", detected_at=123
    )
    assert message.session_id is None


def test_condition_report_rejects_an_unlisted_condition() -> None:
    with pytest.raises(ValidationError):
        ConditionReportMessage(
            session_id="session-1", condition="not_a_real_condition", detected_at=123
        )


def test_error_message_accepts_the_amended_queue_overflow_code() -> None:
    message = ErrorMessage(session_id="session-1", error_code="queue_overflow")
    assert message.error_code == "queue_overflow"
    assert message.message is None


def test_error_message_rejects_a_code_outside_spec_7_3s_enum() -> None:
    with pytest.raises(ValidationError):
        ErrorMessage(session_id="session-1", error_code="not_a_real_code")


def test_clock_sync_request_carries_edge_send_ms() -> None:
    message = ClockSyncRequestMessage(edge_send_ms=1000)
    assert message.model_dump() == {
        "type": "clock_sync_request", "edge_send_ms": 1000}


def test_clock_sync_response_echoes_and_adds_host_clocks() -> None:
    message = ClockSyncResponseMessage(
        edge_send_ms=1000, host_recv_ms=1050, host_send_ms=1060
    )
    assert message.model_dump() == {
        "type": "clock_sync_response",
        "edge_send_ms": 1000,
        "host_recv_ms": 1050,
        "host_send_ms": 1060,
    }


def test_response_message_is_the_existing_pipeline_contract_not_a_second_copy() -> None:
    # Phase 14 must not redefine `response` (SPEC 8.1) -- it's already
    # pipeline.contracts.ResponsePayload. This test guards against a
    # future edit accidentally introducing a second, drifting definition
    # in api/ws/messages.py.
    from api.ws import messages

    assert messages.ResponsePayload is ResponsePayload


@pytest.mark.parametrize(
    ("message_type", "model_cls"),
    [
        ("start_audio", StartAudioMessage),
        ("end_audio", EndAudioMessage),
        ("condition_report", ConditionReportMessage),
        ("clock_sync_request", ClockSyncRequestMessage),
    ],
)
def test_uplink_message_types_table_matches_each_models_literal(message_type, model_cls) -> None:
    assert UPLINK_MESSAGE_TYPES[message_type] is model_cls


def test_parse_uplink_message_dispatches_by_type_field() -> None:
    parsed = parse_uplink_message(
        {"type": "end_audio", "session_id": "session-1", "frame_count": 3}
    )
    assert isinstance(parsed, EndAudioMessage)
    assert parsed.frame_count == 3


def test_parse_uplink_message_rejects_an_unrecognized_type() -> None:
    with pytest.raises(UnknownMessageTypeError):
        parse_uplink_message(
            {"type": "not_a_real_message", "session_id": "session-1"})


def test_parse_uplink_message_propagates_validation_errors_from_the_matched_model() -> None:
    # type is recognized, but the payload for that type is malformed --
    # this should raise the model's own ValidationError, not
    # UnknownMessageTypeError.
    with pytest.raises(ValidationError):
        parse_uplink_message(
            {"type": "start_audio", "session_id": "session-1"})


def test_parse_uplink_message_rejects_a_missing_type_field() -> None:
    with pytest.raises(UnknownMessageTypeError):
        parse_uplink_message({"session_id": "session-1"})


def test_response_is_not_a_parseable_uplink_message() -> None:
    # response (SPEC 8.1) is host -> edge only; the host never needs to
    # parse one of its own outgoing messages back in.
    assert "response" not in UPLINK_MESSAGE_TYPES
