"""WP-102 composition root.

This is the only module that assembles concrete audio and AI dependencies for
the host-only pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

from adapters.affect import ClassifierAffectDetector, DevelopmentAffectDetector
from adapters.llm import OllamaLLMAdapter
from adapters.llm.intent_classifier import OllamaIntentClassifier
from adapters.stt import WhisperSTTAdapter
from adapters.tts import PiperTTSAdapter
from audio.capture import MicrophoneAudioInput
from audio.playback import SpeakerAudioOutput
from audio.resample import to_pcm16_16k
from config.settings import Settings, get_settings
from pipeline.host_pipeline import HostPipeline
from storage.sqlite_store import SQLiteStore

if TYPE_CHECKING:
    from pipeline.interaction import InteractionRunner
    from pipeline.worker import InteractionWorker


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HostComponents:
    """The WP-103 runtime's assembled dependencies.

    Replaces the positional 5-tuple ``build_host_components`` used to return
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
    affect_detector: ClassifierAffectDetector | DevelopmentAffectDetector
    runner: InteractionRunner
    worker: InteractionWorker


def build_host_pipeline(settings: Settings | None = None) -> HostPipeline:
    """Assemble the host pipeline from the configured runtime components."""
    settings = settings or get_settings()
    return HostPipeline(
        audio_input=MicrophoneAudioInput(settings),
        stt=WhisperSTTAdapter(settings),
        llm=OllamaLLMAdapter(settings),
        tts=PiperTTSAdapter(settings),
        audio_output=SpeakerAudioOutput(settings),
    )


def _warm_up_llm(settings: Settings) -> None:
    """Force-load ``settings.llm_model`` into Ollama before the first real
    interaction, so a cold model-load doesn't eat into the per-turn
    ``intent_timeout_s`` / ``reasoning_timeout_s`` budget (D5).

    ``OllamaIntentClassifier`` and ``OllamaLLMAdapter`` both read
    ``settings.llm_model`` (D4: no model split yet), so one warm-up call
    here covers both call sites -- Ollama keys its in-memory model cache by
    model name, not by caller.

    An empty prompt is Ollama's documented "load into memory, don't
    generate" call. The timeout here (``llm_warmup_timeout_s``) is
    deliberately generous and separate from the per-turn D5 budget: this is
    meant to pay the cold-load cost once, here, instead of inside a live
    interaction's 5-30s window.

    Best-effort: a failure here (Ollama unreachable, model not pulled,
    etc.) is logged, not raised -- it must not prevent composition-root
    construction. The identical failure will surface as a real, correctly
    classified ``IntentClassifierError``/``LLMAdapterError`` on the first
    actual interaction (F4), which is where SYNCRO's failure boundary is
    designed to handle it. (This contract is intentionally unchanged by
    the two fixes below -- see test_warm_up_llm_failure_is_swallowed_not_raised.)

    Bug fixed here (1/2): the previous version only caught
    ``requests.RequestException`` (connection-level failures) and never
    checked the HTTP response status. A normal HTTP error response -- e.g.
    Ollama's 404 "model not found, try pulling it first" -- raises no
    exception in ``requests``, so the old code treated that as a silent
    success: nothing was logged, ``ollama ps`` stayed empty, and the real
    interaction ran straight into the same failure five seconds later with
    no warning printed anywhere. Adding ``response.raise_for_status()``
    makes that case visible here, where it actually happened.

    Bug fixed here (2/2): the previous version's warm-up payload omitted
    ``options.num_ctx`` entirely, so it loaded the model at Ollama's
    default context length. ``OllamaIntentClassifier``/``OllamaLLMAdapter``
    both request ``num_ctx=settings.ollama_num_ctx``. Ollama sizes the KV
    cache at load time, so a request with a *different* num_ctx than the
    currently-loaded one forces a full reload -- meaning the previous
    warm-up call was silently warming the wrong configuration, and the
    first real interaction paid the ~6s load cost again anyway (confirmed
    via a manual curl: load_duration dominated total_duration, while
    eval_duration for the same model, once genuinely warm, was ~50
    tokens/sec -- generation was never the bottleneck). Passing the same
    ``num_ctx`` here is what actually makes the warm model reusable.
    """
    try:
        response = requests.post(
            f"{settings.ollama_url.rstrip('/')}/api/generate",
            json={
                "model": settings.llm_model,
                "prompt": "",
                "stream": False,
                "keep_alive": settings.ollama_keep_alive,
                "options": {"num_ctx": settings.ollama_num_ctx},
            },
            timeout=settings.llm_warmup_timeout_s,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        message = (
            f"LLM warm-up call failed (model={settings.llm_model!r}, "
            f"url={settings.ollama_url!r}): {exc}. The first real "
            "interaction will very likely hit intent_timeout_s/"
            "reasoning_timeout_s trying to cold-load this model instead."
        )
        logger.warning(message)


def build_host_components(
    settings: Settings | None = None, *, affect_detector=None
) -> HostComponents:
    """Assemble the host components and graph dependencies used by the runtime."""
    settings = settings or get_settings()
    _warm_up_llm(settings)
    store = SQLiteStore(settings.db_path)
    stt = WhisperSTTAdapter(settings)
    intent_classifier = OllamaIntentClassifier(settings)
    llm = OllamaLLMAdapter(settings)
    tts = PiperTTSAdapter(settings)
    audio_input = MicrophoneAudioInput(settings)
    audio_output = SpeakerAudioOutput(settings)

    from pipeline.graph import build_dialogue_graph

    if affect_detector is None:
        backend = settings.affect_detector_backend.strip().lower()
        if backend == "development":
            affect_detector = DevelopmentAffectDetector()
        elif backend == "classifier":
            try:
                affect_detector = ClassifierAffectDetector(
                    settings.affect_classifier_path)
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

    # F3: the runner is part of the composition root so every caller
    # shares the same interaction lifecycle instead of rebuilding graph -> TTS
    # -> trace orchestration independently. Per F1/Phase 6, the graph output
    # node no longer persists the trace itself -- it returns a `pending_trace`
    # in state, and the runner (below) is the single place that finalizes and
    # writes it.
    from pipeline.interaction import InteractionRunner

    runner = InteractionRunner(
        graph=graph,
        store=store,
        tts=tts,
        resampler=to_pcm16_16k,
    )

    # S1: the worker is constructed here so it shares the composition root's
    # single runner instance, but it is deliberately *not* started -- start()
    # spawns a background thread, and doing that as a side effect of building
    # components would surprise every test/caller that just wants the
    # assembled dependencies without a thread running. Starting/stopping it
    # is a lifecycle concern that belongs with whatever owns the process
    # lifetime (WP-105's FastAPI `lifespan`, Phase 14), not with assembly.
    from pipeline.worker import InteractionWorker

    worker = InteractionWorker(
        runner=runner, maxsize=settings.interaction_queue_maxsize
    )

    return HostComponents(
        graph=graph,
        store=store,
        audio_input=audio_input,
        audio_output=audio_output,
        tts=tts,
        affect_detector=affect_detector,
        runner=runner,
        worker=worker,
    )
