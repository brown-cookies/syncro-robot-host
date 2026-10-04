"""What each dialogue-graph stage records (OBS-LOG FR-O4, FR-O5, FR-O10).

One table decides, per stage, which fields appear on ``stage_started``
(input) and ``stage_completed`` (output), and which keys get a DEBUG-only
before/after ``state_snapshot`` diff. Nothing here serializes whole state:
every field is selected by name, and the selectors are written so that
free text and raw audio never leave as values:

- text fields (``transcript``, ``draft_response``, ``final_response``) are
  passed under those exact names so central redaction reduces them to
  length + hash (full text only with LOG_LEVEL=DEBUG and LOG_INCLUDE_TEXT=true)
- raw audio is reduced to a sample count
- ``slots`` can carry user words under arbitrary keys, so only its key names
  are recorded

Selectors never raise: a broken selector yields ``{}`` rather than failing the
stage (observability must not change behavior, spec Section 2).

The same table says when a stage's normal work is bypassed. ``skip`` is
evaluated on the stage's input state; a non-None reason ends the stage as
``stage_skipped`` (instead of ``stage_completed``). The predicate mirrors the
bypass condition inside the node itself, so keep the two in step; the
integration tests assert that a skipped stage really did not do its work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

State = Mapping[str, Any]
Selector = Callable[[State], dict[str, Any]]
SkipRule = Callable[[State], "str | None"]

SKIP_CLARIFICATION_ONLY = "clarification_only"


def _skip_when_clarifying(state: State) -> str | None:
    """Low-confidence intents are clarification-only: no context lookup, no LLM call."""
    return SKIP_CLARIFICATION_ONLY if state.get("proposed_action") == "clarify" else None


def _audio(state: State) -> dict[str, Any]:
    audio = state.get("audio")
    return {
        "audio_samples": int(getattr(audio, "size", 0) or 0),
        "sample_rate": state.get("sample_rate"),
    }


def _context_counts(state: State) -> dict[str, Any]:
    ctx = state.get("context") or {}
    return {
        "task_count": len(ctx.get("tasks") or []),
        "overdue_count": len(ctx.get("overdue_tasks") or []),
    }


def _pick(*keys: str) -> Selector:
    return lambda state: {key: state.get(key) for key in keys}


def _intent_out(update: State) -> dict[str, Any]:
    return {
        "intent": update.get("intent"),
        "intent_confidence": update.get("intent_confidence"),
        "slot_keys": sorted(str(key) for key in (update.get("slots") or {})),
        "clarify": update.get("proposed_action") == "clarify",
    }


def _context_out(update: State) -> dict[str, Any]:
    return {
        "retrieved_context_ids": list(update.get("retrieved_context_ids") or []),
        **_context_counts(update),
        "deadline_proximity": update.get("deadline_proximity"),
    }


def _llm_in(state: State) -> dict[str, Any]:
    return {
        **_pick("intent", "intent_confidence", "proposed_action", "transcript")(state),
        **_context_counts(state),
    }


def _output_out(update: State) -> dict[str, Any]:
    payload = update.get("response_payload") or {}
    return {
        "state_tag": payload.get("state_tag"),
        "policy_rule": payload.get("policy_rule"),
        "lead_time_min": payload.get("lead_time_min"),
    }


@dataclass(frozen=True, slots=True)
class StageIO:
    inputs: Selector
    outputs: Selector
    # Keys whose before/after is logged as a DEBUG state_snapshot diff. Only
    # stages that create or rewrite a value worth watching list any.
    diff_keys: tuple[str, ...] = ()
    # Returns a reason when the stage's normal work is bypassed, else None.
    skip: SkipRule | None = None


STAGE_IO: dict[str, StageIO] = {
    "stt": StageIO(_audio, _pick("transcript")),
    "affect": StageIO(_audio, _pick("affect_level", "degradation_reason")),
    "intent": StageIO(_pick("transcript"), _intent_out),
    "context": StageIO(
        _pick("intent", "proposed_action"), _context_out, skip=_skip_when_clarifying
    ),
    # draft_response / proposed_action are created here; this is where the
    # mutation-claim guard may replace the draft.
    "llm": StageIO(
        _llm_in,
        _pick("proposed_action", "draft_response"),
        diff_keys=("draft_response", "proposed_action"),
        skip=_skip_when_clarifying,
    ),
    # Policy rewrites the response (prefix per rule) and may force
    # deadline_proximity to n/a for non-governed intents.
    "policy": StageIO(
        _pick("intent", "affect_level", "deadline_proximity", "draft_response"),
        _pick(
            "policy_rule", "action_taken", "deadline_proximity",
            "lead_time_min", "reminder_outcome", "final_response",
        ),
        diff_keys=("final_response", "deadline_proximity"),
    ),
    "output": StageIO(
        _pick(
            "policy_rule", "action_taken", "affect_level",
            "degradation_reason", "final_response",
        ),
        _output_out,
    ),
}


def _safe(selector: Selector, state: State) -> dict[str, Any]:
    try:
        return selector(state)
    except Exception:  # noqa: BLE001 - observability must never fail a stage
        return {}


def describe_input(stage: str, state: State) -> dict[str, Any]:
    io = STAGE_IO.get(stage)
    return _safe(io.inputs, state) if io else {}


def describe_output(stage: str, update: State) -> dict[str, Any]:
    io = STAGE_IO.get(stage)
    return _safe(io.outputs, update) if io else {}


def diff_keys(stage: str) -> tuple[str, ...]:
    io = STAGE_IO.get(stage)
    return io.diff_keys if io else ()


# Central redaction blanks any non-string value stored under a text-named key
# (draft_response, final_response, ...), and a diff stores a before/after pair
# there. Left alone, that would hide the hashes by default and the text even
# with LOG_INCLUDE_TEXT=true. The diff labels those keys neutrally instead; it
# still honors the same hash-only / opt-in rules (Emitter.diff masks by type).
_DIFF_LABEL = {"draft_response": "draft", "final_response": "final"}


def diff_views(
    stage: str, before: State, after: State
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Only the stage's named keys, relabelled; never the whole state."""
    keys = diff_keys(stage)
    label = lambda key: _DIFF_LABEL.get(key, key)  # noqa: E731
    return (
        {label(k): before[k] for k in keys if k in before},
        {label(k): after[k] for k in keys if k in after},
        [label(k) for k in keys],
    )


def skip_reason(stage: str, state: State) -> str | None:
    """Why this stage's normal work is bypassed for ``state``, or None."""
    io = STAGE_IO.get(stage)
    if io is None or io.skip is None:
        return None
    try:
        return io.skip(state)
    except Exception:  # noqa: BLE001 - observability must never fail a stage
        return None
