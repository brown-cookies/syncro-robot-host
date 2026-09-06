"""WP-103 Node 1A: speech transcription."""

from __future__ import annotations

from pipeline.state import DialogueState


def make_stt_node(stt):
    def stt_node(state: DialogueState) -> DialogueState:
        audio = state.get("audio")
        sample_rate = state.get("sample_rate")
        if audio is None or sample_rate is None:
            raise RuntimeError("Node 1 STT requires audio and sample_rate in DialogueState.")
        transcript = stt.transcribe(audio, sample_rate=sample_rate)
        if not transcript.strip():
            raise ValueError("Node 1 STT returned an empty transcript.")
        return {"transcript": transcript.strip()}
    return stt_node
