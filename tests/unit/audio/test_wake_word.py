from uuid import uuid4

import pytest

from audio.wake_word import StartAudioMessage, WakeWordMetadata


def test_start_audio_contract_accepts_spec_fields() -> None:
    """Verify that start audio contract accepts spec fields."""
    msg = StartAudioMessage(
        session_id=uuid4(),
        user_id="user-1",
        wake_word_detected_at=123456,
    )
    assert msg.type == "start_audio"
    assert msg.wake_word_detected_at == 123456


def test_start_audio_rejects_negative_timestamp() -> None:
    """Verify that start audio rejects negative timestamp."""
    with pytest.raises(ValueError):
        StartAudioMessage(
            session_id=uuid4(),
            user_id="user-1",
            wake_word_detected_at=-1,
        )


def test_start_audio_rejects_unknown_fields() -> None:
    """Verify that start audio rejects unknown fields."""
    with pytest.raises(ValueError):
        StartAudioMessage(
            session_id=uuid4(),
            user_id="user-1",
            wake_word_detected_at=1,
            keyword="syncro",
        )


def test_wake_word_metadata_rejects_negative_timestamp() -> None:
    """Verify that wake word metadata rejects negative timestamp."""
    with pytest.raises(ValueError):
        WakeWordMetadata(-1)
