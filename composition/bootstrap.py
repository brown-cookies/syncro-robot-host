"""WP-102 composition root.

This is the only module that assembles concrete audio and AI dependencies for
the host-only pipeline.
"""

from __future__ import annotations

from adapters.llm import OllamaLLMAdapter
from adapters.stt import WhisperSTTAdapter
from adapters.tts import PiperTTSAdapter
from audio.capture import MicrophoneAudioInput
from audio.playback import SpeakerAudioOutput
from config.settings import Settings, get_settings
from pipeline.host_pipeline import HostPipeline


def build_wp102_pipeline(settings: Settings | None = None) -> HostPipeline:
    settings = settings or get_settings()
    return HostPipeline(
        audio_input=MicrophoneAudioInput(settings),
        stt=WhisperSTTAdapter(settings),
        llm=OllamaLLMAdapter(settings),
        tts=PiperTTSAdapter(settings),
        audio_output=SpeakerAudioOutput(settings),
    )
