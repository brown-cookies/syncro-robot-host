from __future__ import annotations

from observability.redaction import REDACTED, hash_text, redact


class _FakeArray:
    shape = (4,)
    dtype = "float32"


def test_secrets_are_redacted_by_key_and_in_strings() -> None:
    out = redact(
        {
            "password": "hunter2",
            "Authorization": "Bearer abc.def",
            "metadata": {"api_key": "k", "token": "t", "max_tokens": 64},
            "message": "call failed: token=abc123 Bearer xyz",
        },
        include_text=False,
    )
    assert out["password"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["metadata"]["api_key"] == REDACTED
    assert out["metadata"]["token"] == REDACTED
    assert out["metadata"]["max_tokens"] == 64  # not a secret
    assert "abc123" not in out["message"] and "xyz" not in out["message"]


def test_raw_audio_and_byte_payloads_are_omitted() -> None:
    out = redact({"audio": [0.1, 0.2], "blob": b"\x00\x01", "arr": _FakeArray()}, include_text=True)
    assert out["audio"] == "[AUDIO OMITTED]"
    assert out["blob"] == "[2 BYTES OMITTED]"
    assert "OMITTED" in out["arr"]


def test_text_is_hash_only_by_default() -> None:
    out = redact({"transcript": "remind me at noon", "final_response": "ok"}, include_text=False)
    assert "transcript" not in out and "final_response" not in out
    assert out["transcript_length"] == 17
    assert out["transcript_hash"] == hash_text("remind me at noon")
    assert len(out["transcript_hash"]) == 16


def test_full_text_only_when_include_text() -> None:
    out = redact({"metadata": {"transcript": "remind me at noon"}}, include_text=True)
    assert out["metadata"]["transcript"] == "remind me at noon"


def test_prompts_never_logged_even_with_include_text() -> None:
    out = redact({"prompt": "system rules...", "system_prompt": "x"}, include_text=True)
    assert "prompt" not in out and "system_prompt" not in out
    assert out["prompt_length"] == 15


def test_redact_does_not_mutate_input() -> None:
    original = {"metadata": {"transcript": "hi", "password": "p"}}
    redact(original, include_text=False)
    assert original == {"metadata": {"transcript": "hi", "password": "p"}}
