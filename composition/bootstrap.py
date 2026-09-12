"""WP-102 composition root.

This is the only module that assembles concrete audio and AI dependencies for
the host-only pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from adapters.llm import OllamaLLMAdapter
from adapters.llm.intent_classifier import OllamaIntentClassifier
from adapters.stt import WhisperSTTAdapter
from adapters.tts import PiperTTSAdapter
from audio.capture import MicrophoneAudioInput
from audio.playback import SpeakerAudioOutput
from config.settings import Settings, get_settings
from pipeline.host_pipeline import HostPipeline
from storage.sqlite_store import SQLiteStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HostComponents:
    """The WP-103 runtime's assembled dependencies.

    Replaces the positional 5-tuple ``build_wp103_components`` used to return
    (finding S2): every new component the sprint adds (runner, request queue,
    session registry, authentication) used to change that tuple's arity and
    break every caller and every test that unpacked it by position. Adding a
    field here is additive and non-breaking for existing callers that access
    fields by name.
    """

    graph: Any
    store: SQLiteStore
    audio_input: Any
    audio_output: Any
    tts: Any
    # Forward-declared so this dataclass's shape doesn't change arity again
    # mid-sprint. Populated once Phase 5 (F3, InteractionRunner) exists;
    # untyped (Any) rather than imported because pipeline.interaction does not
    # exist yet at this phase.
    runner: Any = None


def build_wp102_pipeline(settings: Settings | None = None) -> HostPipeline:
    """Assemble the host pipeline from the configured runtime components."""
    settings = settings or get_settings()
    return HostPipeline(
        audio_input=MicrophoneAudioInput(settings),
        stt=WhisperSTTAdapter(settings),
        llm=OllamaLLMAdapter(settings),
        tts=PiperTTSAdapter(settings),
        audio_output=SpeakerAudioOutput(settings),
    )


def build_wp103_components(
    settings: Settings | None = None, *, affect_detector=None
) -> HostComponents:
    """Assemble the host components and graph dependencies used by the runtime."""
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
        from adapters.affect import ClassifierAffectDetector, DevelopmentAffectDetector

        backend = settings.affect_detector_backend.strip().lower()
        if backend == "development":
            affect_detector = DevelopmentAffectDetector()
        elif backend == "classifier":
            try:
                affect_detector = ClassifierAffectDetector(settings.affect_classifier_path)
            except (FileNotFoundError, RuntimeError) as exc:
                logger.warning(
                    "WP-104 classifier unavailable at %s; using development affect detector: %s",
                    settings.affect_classifier_path,
                    exc,
                )
                affect_detector = DevelopmentAffectDetector()
        else:
            raise ValueError(
                "AFFECT_DETECTOR_BACKEND must be 'development' or 'classifier'"
            )

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
    return HostComponents(
        graph=graph,
        store=store,
        audio_input=audio_input,
        audio_output=audio_output,
        tts=tts,
    )
