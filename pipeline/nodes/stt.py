"""WP-103 Node 1A: speech transcription."""

from __future__ import annotations

from observability import NULL_EMITTER, Emitter
from pipeline.state import DialogueState


def make_stt_node(stt, emitter: Emitter = NULL_EMITTER):
    """Create the speech-to-text graph node with its injected adapter."""
    def stt_node(state: DialogueState) -> DialogueState:
        """Transcribe request audio and place the result into dialogue state."""
        audio = state.get("audio")
        sample_rate = state.get("sample_rate")
        if audio is None or sample_rate is None:
            raise RuntimeError("Node 1 STT requires audio and sample_rate in DialogueState.")
        # OBS-LOG FR-O6: the model call is its own boundary inside the stage.
        # ``transcript`` is a redacted key: events carry length + hash unless
        # LOG_LEVEL=DEBUG and LOG_INCLUDE_TEXT=true.
        with emitter.model_inference(
            trace_id=state.get("trace_id") or "",
            component="stt",
            session_id=state.get("session_id"),
            model_name=getattr(stt, "model_name", None),
        ) as call:
            transcript = stt.transcribe(audio, sample_rate=sample_rate)
            call.result["transcript"] = transcript
        if not transcript.strip():
            raise ValueError("Node 1 STT returned an empty transcript.")
        return {"transcript": transcript.strip()}
    return stt_node
