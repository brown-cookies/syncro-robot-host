"""Host-side wake-word event contract.

The host SPEC does not prescribe or implement the wake-word engine. Wake-word
selection, model training, and on-device detection are edge-side concerns.
The host receives a SPEC-defined ``start_audio`` message containing the
edge-confirmed wake-word timestamp and carries that metadata into processing.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StartAudioMessage(BaseModel):
    """SPEC Section 7.3 ``start_audio`` message."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["start_audio"] = "start_audio"
    session_id: UUID
    user_id: str = Field(min_length=1)
    wake_word_detected_at: int = Field(ge=0)


class WakeWordMetadata:
    """Marker type for edge-supplied wake-word metadata."""

    __slots__ = ("wake_word_detected_at",)

    def __init__(self, wake_word_detected_at: int) -> None:
        if wake_word_detected_at < 0:
            raise ValueError("wake_word_detected_at must be non-negative")
        self.wake_word_detected_at = wake_word_detected_at
