"""Transient reminder-reference resolution for the Phase 17 execution boundary."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from pipeline.contracts import ExecutableIntent


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    """One user-scoped pending reminder that can be selected for execution."""

    trace_id: str
    label: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class PendingReferenceClarification:
    """Transient continuation state for an unresolved reminder reference."""

    user_id: str
    intent: ExecutableIntent
    intent_confidence: float
    slots: dict[str, Any]
    candidates: tuple[ReferenceCandidate, ...]


class ReferenceClarificationStore:
    """Bounded, process-local continuation state for reference clarification.

    This state is deliberately not persisted to SQLite and is not part of the
    decision-trace schema. A process restart therefore drops unfinished
    clarifications rather than guessing a target from stale state.
    """

    def __init__(self, *, max_entries: int = 1024) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._lock = RLock()
        self._pending: dict[str, PendingReferenceClarification] = {}
        self._order: list[str] = []

    def put(self, value: PendingReferenceClarification) -> None:
        with self._lock:
            self._pending[value.user_id] = value
            if value.user_id in self._order:
                self._order.remove(value.user_id)
            self._order.append(value.user_id)
            while len(self._order) > self._max_entries:
                oldest_user_id = self._order.pop(0)
                self._pending.pop(oldest_user_id, None)

    def get(self, user_id: str) -> PendingReferenceClarification | None:
        with self._lock:
            return self._pending.get(user_id)

    def pop(self, user_id: str) -> PendingReferenceClarification | None:
        with self._lock:
            value = self._pending.pop(user_id, None)
            if value is not None and user_id in self._order:
                self._order.remove(user_id)
            return value

    def clear(self, user_id: str) -> None:
        self.pop(user_id)


def build_clarification_prompt(candidates: tuple[ReferenceCandidate, ...]) -> str:
    """Build a bounded clarification question from validated candidates."""
    if not candidates:
        raise ValueError("cannot build a clarification prompt without candidates")
    choices = " ".join(
        f"{index}. {candidate.label}"
        for index, candidate in enumerate(candidates, start=1)
    )
    return f"Which reminder do you mean? {choices}"


def resolve_clarification_answer(
    transcript: str,
    candidates: tuple[ReferenceCandidate, ...],
) -> ReferenceCandidate | None | object:
    """Resolve a clarification answer when it identifies exactly one candidate.

    Returns:
      - a ``ReferenceCandidate`` for a unique match;
      - ``None`` when no candidate can be identified;
      - ``AMBIGUOUS`` when multiple candidates are equally plausible.

    Matching is deliberately bounded and deterministic: ordinal answers,
    exact label/title mentions, and normalized token overlap are accepted.
    The resolver never creates a trace id or chooses a candidate outside the
    previously presented candidate set.
    """
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    normalized = _normalize(transcript)
    if not normalized:
        return None

    ordinal_index = _ordinal_index(normalized)
    if ordinal_index is not None:
        if 0 <= ordinal_index < len(candidates):
            return candidates[ordinal_index]
        return None

    exact_matches = [
        candidate
        for candidate in candidates
        if _contains_phrase(normalized, _normalize(candidate.title or candidate.label))
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return AMBIGUOUS

    scores: list[tuple[ReferenceCandidate, float]] = []
    answer_tokens = _meaningful_tokens(normalized)
    if not answer_tokens:
        return None

    for candidate in candidates:
        title_tokens = _meaningful_tokens(_normalize(candidate.title or candidate.label))
        if not title_tokens:
            continue
        overlap = len(answer_tokens.intersection(title_tokens))
        if overlap == 0:
            continue
        score = overlap / len(title_tokens)
        scores.append((candidate, score))

    if not scores:
        return None

    scores.sort(key=lambda item: item[1], reverse=True)
    best_candidate, best_score = scores[0]
    if best_score < 0.5:
        return None
    if len(scores) > 1 and scores[1][1] == best_score:
        return AMBIGUOUS
    return best_candidate


class _Ambiguous:
    pass


AMBIGUOUS = _Ambiguous()

_STOP_WORDS = frozenset({
    "a", "an", "and", "for", "i", "it", "me", "one", "please", "reminder",
    "that", "the", "this", "to", "which", "you", "your",
})


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_phrase(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return needle in haystack


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token.strip(".,!?;:()[]{}\"'")
        for token in value.split()
        if token.strip(".,!?;:()[]{}\"'") and token not in _STOP_WORDS
    }


def _ordinal_index(value: str) -> int | None:
    tokens = value.split()
    if len(tokens) > 4:
        return None
    mapping = {
        "1": 0,
        "first": 0,
        "2": 1,
        "second": 1,
        "3": 2,
        "third": 2,
        "4": 3,
        "fourth": 3,
        "5": 4,
        "fifth": 4,
    }
    for token in tokens:
        if token in mapping:
            return mapping[token]
    # Cardinal words such as "one" only count as an ordinal when the answer
    # is otherwise short. This prevents "the call one" from being mistaken
    # for candidate 1 when it is actually a semantic title reference.
    if len(tokens) <= 2:
        cardinal = {
            "one": 0,
            "two": 1,
            "three": 2,
            "four": 3,
            "five": 4,
        }
        for token in tokens:
            if token in cardinal:
                return cardinal[token]
    return None
