"""Run the WP-102 real host-only acceptance path.

Usage:
    python -m scripts.run_wp102
"""

from __future__ import annotations

import sys

from adapters.stt import STTAdapterError
from adapters.tts import TTSAdapterError
from config.settings import get_settings
from pipeline.host_pipeline import PipelineStageError
from composition.bootstrap import build_wp102_pipeline


def main() -> int:
    """Run the command-line entry point for this module."""
    settings = get_settings()
    print("WP-102 host-only pipeline")
    print(f"  Ollama:  {settings.ollama_url}  model={settings.llm_model}")
    print(
        f"  Whisper: size={settings.stt_model_size} "
        f"compute={settings.stt_compute_type} device={settings.stt_device}"
    )
    print(f"  Piper:   model_path={settings.piper_model_path}")
    print()

    try:
        pipeline = build_wp102_pipeline(settings)
    except STTAdapterError as exc:
        print(
            f"[ERR-2] STT adapter failed to initialize: {exc}", file=sys.stderr)
        return 1
    except TTSAdapterError as exc:
        print(
            f"[ERR-4] TTS adapter failed to initialize: {exc}", file=sys.stderr)
        return 1

    print(
        f"Recording {settings.audio_capture_seconds:.0f}s from the USB microphone -- speak now..."
    )
    try:
        result, _audio, _sample_rate = pipeline.run_once()
    except PipelineStageError as exc:
        print(f"\n[{exc.stage}] WP-102 run FAILED: {exc.cause}",
              file=sys.stderr)
        return 1
    print("\n--- WP-102 run complete ---")
    print(f"Transcript: {result.transcript!r}")
    print(f"Response:   {result.response_text!r}")
    print("Stage durations (s):")
    for stage, duration in result.stage_durations_s.items():
        print(f"  {stage:14s} {duration:6.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
