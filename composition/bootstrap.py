"""WP-102 composition root.

This is the only module that assembles concrete audio and AI dependencies for
the host-only pipeline.
"""

from __future__ import annotations

from adapters.llm import OllamaLLMAdapter
from adapters.llm.intent_classifier import OllamaIntentClassifier
from adapters.stt import WhisperSTTAdapter
from adapters.tts import PiperTTSAdapter
from audio.capture import MicrophoneAudioInput
from audio.playback import SpeakerAudioOutput
from config.settings import Settings, get_settings
from pipeline.host_pipeline import HostPipeline
from storage.sqlite_store import SQLiteStore


def build_wp102_pipeline(settings: Settings | None = None) -> HostPipeline:
    settings = settings or get_settings()
    return HostPipeline(
        audio_input=MicrophoneAudioInput(settings),
        stt=WhisperSTTAdapter(settings),
        llm=OllamaLLMAdapter(settings),
        tts=PiperTTSAdapter(settings),
        audio_output=SpeakerAudioOutput(settings),
    )


def build_wp103_components(settings: Settings | None = None, *, affect_detector=None):
    """Assemble the WP-103 graph from concrete host adapters and SQLite.

    This composition root keeps dependency construction outside the LangGraph
    nodes, so the graph remains testable with technology-neutral fakes.
    """
    settings = settings or get_settings()
    store = SQLiteStore(settings.db_path)
    stt = WhisperSTTAdapter(settings)
    intent_classifier = OllamaIntentClassifier(settings)
    llm = OllamaLLMAdapter(settings)
    tts = PiperTTSAdapter(settings)
    audio_input = MicrophoneAudioInput(settings)
    audio_output = SpeakerAudioOutput(settings)

    from pipeline.graph import build_dialogue_graph

    if affect_detector is None:
        from adapters.affect import DevelopmentAffectDetector

        affect_detector = DevelopmentAffectDetector()

    graph = build_dialogue_graph(
        stt=stt,
        intent_classifier=intent_classifier,
        llm=llm,
        store=store,
        affect_detector=affect_detector,
        confidence_threshold=settings.intent_confidence_threshold,
        context_top_k=settings.context_top_k,
        deadline_proximity_hours=settings.deadline_proximity_hours,
        grace_window_minutes=settings.grace_window_minutes,
        default_lead_time=settings.lead_time_default,
    )
    return graph, store, audio_input, audio_output, tts
