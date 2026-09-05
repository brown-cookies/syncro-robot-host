"""WP-103 Node 3: structured Ollama reasoning."""

from __future__ import annotations

import json
import re

from pipeline.state import DialogueState


def make_llm_node(llm):
    def llm_node(state: DialogueState) -> DialogueState:
        if state.get("proposed_action") == "clarify":
            final_response = state.get("final_response")
            if final_response is None:
                raise RuntimeError("Node 3 clarification path requires final_response in DialogueState.")
            return {"draft_response": final_response, "proposed_action": "clarify"}

        intent = state.get("intent")
        intent_confidence = state.get("intent_confidence")
        transcript = state.get("transcript")
        if intent is None or intent_confidence is None or transcript is None:
            raise RuntimeError(
                "Node 3 LLM reasoning requires intent, intent_confidence, "
                "and transcript in DialogueState."
            )

        context = state.get("context", {})
        reasoning_context = _select_context_for_request(transcript, context)

        prompt = f"""You are the SYNCRO dialogue reasoner.
Return ONLY JSON: {{"response_text":"...","proposed_action":"..."}}.

User utterance: {transcript}
Intent: {intent}
Intent confidence: {intent_confidence}
Slots: {json.dumps(state.get("slots", {}), ensure_ascii=True)}
Retrieved context: {json.dumps(reasoning_context, ensure_ascii=True)}

Context-selection rules:
- If the user asks for overdue task(s), use ONLY the overdue_tasks list.
- Do not enumerate upcoming/non-overdue tasks when answering an overdue-task request.
- If there are no overdue tasks, say that there are no overdue tasks.
- For other task-list requests, use the relevant task lists in the retrieved context.

Execution boundary:
- Node 3 ONLY drafts a response and proposed action. It does NOT execute database or task mutations.
- Never claim that a task was added, rescheduled, snoozed, or dismissed as completed.
- For add_task or reschedule_task, phrase the output as a proposed/requested action, not as a completed mutation.
- For snooze_reminder or dismiss_reminder, describe the requested reminder action as a proposal unless an executor explicitly confirms success.

Write a useful natural-language response based on the intent, utterance, and context.
Never output motor commands or low-level hardware instructions.
"""
        raw = llm.generate(prompt)
        parsed = _parse_json(raw)
        response_text = parsed.get("response_text")
        proposed_action = parsed.get("proposed_action", "respond")
        if not isinstance(response_text, str) or not response_text.strip():
            raise ValueError("Node 3 returned an empty response_text.")
        if not isinstance(proposed_action, str) or not proposed_action.strip():
            proposed_action = "respond"

        response_text = _reject_unexecuted_mutation_claim(
            intent, response_text.strip()
        )
        return {"draft_response": response_text, "proposed_action": proposed_action.strip()}
    return llm_node


def _select_context_for_request(
    transcript: str,
    context: dict[str, object],
) -> dict[str, object]:
    """Select the context relevant to the user's explicit request scope."""
    normalized = transcript.casefold()
    overdue_terms = ("overdue", "past due", "past-due", "late task", "late tasks")
    if any(term in normalized for term in overdue_terms):
        return {
            "overdue_tasks": context.get("overdue_tasks", []),
            "recent_routine": context.get("recent_routine"),
        }
    return context


def _reject_unexecuted_mutation_claim(intent: str, response_text: str) -> str:
    """Degrade unsafe mutation claims instead of crashing the graph.

    Node 3 is a drafting boundary: without an executor it must not claim that
    a mutation already happened. Matching uses word boundaries, explicit
    negation, and prospective language so ordinary wording does not trigger it.
    """
    mutation_terms = {
        "add_task": (r"\badd(?:ed)?\b", r"\bcreated\b", r"\bsaved\b", r"\bscheduled\b"),
        "reschedule_task": (r"\brescheduled\b", r"\bmoved\b", r"\bupdated\b"),
        "snooze_reminder": (r"\bsnoozed\b", r"\bpostponed\b", r"\bdelayed\b"),
        "dismiss_reminder": (r"\bdismissed\b", r"\bcleared\b"),
    }
    terms = mutation_terms.get(intent)
    if not terms:
        return response_text

    lowered = response_text.casefold()
    mutation_match = next(
        (match for term in terms if (match := re.search(term, lowered))),
        None,
    )
    if mutation_match is None:
        return response_text

    # Evaluate only the sentence containing the mutation verb.
    sentence_start = max(lowered.rfind(".", 0, mutation_match.start()), lowered.rfind("!", 0, mutation_match.start()), lowered.rfind("?", 0, mutation_match.start())) + 1
    sentence_end_candidates = [
        index for punctuation in (".", "!", "?")
        if (index := lowered.find(punctuation, mutation_match.end())) >= 0
    ]
    sentence_end = min(sentence_end_candidates, default=len(lowered))
    sentence = lowered[sentence_start:sentence_end].strip()
    prefix = lowered[sentence_start:mutation_match.start()]

    if re.search(
        r"(?:\b(?:not|never|haven't|have not|hasn't|has not|wasn't|was not|isn't|is not)\b[^.!?]{0,40}$|\bnothing\s+(?:was|has been|is)\s*$)",
        prefix,
    ):
        return response_text

    # Prospective/proposal wording is exactly what Node 3 is allowed to do.
    if re.search(
        r"\b(?:can|could|may|might|will|would|should|shall)\b[^.!?]{0,30}$|\blet\s+me\b[^.!?]{0,30}$|\bi(?:'m| am)\s+going\s+to\b[^.!?]{0,30}$",
        prefix,
    ):
        return response_text

    completion = re.search(
        r"(?:\b(?:i(?:'ve| have)|we(?:'ve| have))\s+(?:already\s+)?|\b(?:done|completed|successfully)\b|\b(?:it's|it has|it was|that was|the task was)\s+)",
        sentence,
    )
    if completion is None:
        return response_text

    return (
        "I can help with that, but I have not executed the change yet. "
        + response_text
    )

def _parse_json(raw: str) -> dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Node 3 returned invalid JSON.")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Node 3 response must be a JSON object.")
    return value
