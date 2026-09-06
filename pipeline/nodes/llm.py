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


# AI-BLOCK-START:mutation-claim-guard
# Mutation-claim safety rule.
#
# Node 3 only drafts text; no executor runs behind it. A reply may therefore
# propose a mutation but must never assert that one has happened. The rule is
# expressed as two reviewable signal sets, evaluated sentence by sentence:
#
#   claim signals   - the shapes English uses to assert completion:
#                     first-person past/perfect ("I added", "I've dismissed"),
#                     passive completion ("it was moved", "this has been
#                     cleared"), a bare participle closing a short sentence
#                     ("Task added."), a completion adverb ("already",
#                     "successfully", "done") beside a completed verb form,
#                     and the shape a model reaches for most readily when it
#                     confirms tersely: a clause opening on the completed verb
#                     itself, with the first-person subject and/or the
#                     auxiliary elided ("Added the task to your list.",
#                     "Cancelled the reminder for you.", "Task added to your
#                     list.", "Went ahead and moved it to 5pm.").
#   blocker signals - the shapes that show the verb is not a completed claim
#                     about this turn: negation, modal or prospective framing,
#                     interrogative framing, and temporal or scope distancing.
#
# A blocker governs the verb of its own clause. Which verb that is does not
# follow from how many words away the blocker sits, so its scope is taken
# structurally: the clause carrying the verb, bounded on the left by the
# nearest clause punctuation (comma, semicolon, colon or spaced dash). Two
# consequences follow, and both are the rule rather than exceptions to it:
#
#   - A discourse marker or interjection standing before that boundary
#     ("No problem, ", "Not a problem - ", "Sure, ") is a separate verbless
#     fragment, so its negator cannot reach across the boundary to the verb,
#     however few words away it sits.
#   - A determiner-negator heading the subject noun phrase ("None of the
#     recurring weekly reminders were dismissed.", "Neither reminder was
#     cleared.") sits inside the clause it negates, so it governs that
#     clause's verb however long the noun phrase is.
#
# Two structural repairs keep a clause whole where punctuation cuts through
# it. A preceding segment ending on a word that cannot close a clause - an
# auxiliary, modal, negator, preposition, coordinator or subordinator - is
# still part of this clause, because the predicate it opened has to continue
# ("I have not, however, dismissed it."). And a segment holding nothing but
# finite auxiliaries has no subject of its own, so its clause began before
# the break and the whole prefix is in scope ("None of the reminders,
# including the weekly ones, were dismissed."). Coordination without
# punctuation stays inside one clause, which is the reading English gives
# it: negation distributes over coordinated predicates.
#
# The elided shape is recognised structurally, not by enumerating phrasings.
# Two facts define it, and both must hold:
#
#   1. Clause-head position. The completed verb stands at the head of a
#      clause - the start of the sentence, or just after a comma, semicolon,
#      colon, dash or coordinator - separated from that head by at most two
#      words. That is what a dropped subject and an elided auxiliary look
#      like positionally, and it is why "Task added." and "Added the task."
#      are one rule rather than two: the verb is clause-initial in both,
#      whether or not a subject noun precedes it.
#   2. Completion complement. The verb is followed by something only a finite
#      verb takes: the end of the sentence ("Added."), an object determiner or
#      pronoun ("the", "it", "that", "your"), an adjunct preposition or
#      particle ("to", "for", "off", "back"), or a single bare word closing
#      the sentence or introducing a colon ("Added task: buy milk.").
#
# The complement requirement is what keeps the participle's adjectival
# reading out of the rule. "Cleared reminders stay in your history." puts a
# bare plural noun after the verb and then continues with the sentence's real
# finite verb, so it never satisfies (2); "Cleared the reminder for you."
# does. Interrogative and offer framings are excluded before this point by
# the question and prospective blockers, so an elliptical question ("Moved to
# 5pm?", "Snoozed until when?") cannot reach it.
#
# Only completed verb forms (past tense / past participle) are candidates, so
# base-form proposals ("I can add that", "Let me add that") never enter the
# rule at all. Every pattern is a bounded alternation over word-boundary
# literals scanned once per sentence, so matching stays linear in the length
# of the response and cannot backtrack catastrophically.

_MUTATION_VERB_FORMS = {
    "add_task": ("added", "created", "saved", "scheduled", "logged"),
    "reschedule_task": (
        "rescheduled",
        "moved",
        "shifted",
        "updated",
        "changed",
    ),
    "snooze_reminder": (
        "snoozed",
        "postponed",
        "delayed",
        "deferred",
        "pushed",
    ),
    "dismiss_reminder": (
        "dismissed",
        "cleared",
        "cancelled",
        "canceled",
        "removed",
        "deleted",
        "closed",
    ),
}

# Words that may sit between the subject or auxiliary and the completed verb
# without changing the assertion ("I have just added it").
_CLAIM_FILLERS = (
    "have|has|had|just|already|now|then|also|finally|successfully|"
    "and|went|gone|ahead|simply|quickly"
)

# Where a clause can begin: the start of the sentence, punctuation that opens
# a new clause, or a coordinator. A subject-dropped completion sits here.
_CLAUSE_HEAD = r"(?:^|[,;:]|\s-+\s|\b(?:and|but|so|then|plus)\s)"

# What may follow a finite completed verb whose subject was dropped: an
# object determiner or pronoun, or an adjunct preposition, particle or
# adverb. A bare noun is deliberately absent - a bare noun is the adjectival
# reading ("Cleared reminders stay ...") the rule must not treat as a claim.
_ELLIPTICAL_OBJECT = (
    "the|this|that|these|those|it|its|them|they|their|theirs|your|yours|"
    "my|mine|our|ours|his|her|hers|a|an|all|both|everything|anything|"
    "another|other|you|us|me|next|new|one|two|three|four|five|six|seven|"
    "eight|nine|ten"
)
_ELLIPTICAL_ADJUNCT = (
    "to|for|from|on|onto|into|at|until|till|by|off|back|over|ahead|out|"
    "down|away|through|forward|with|as|around|under|"
    "again|already|now|successfully|instead|too|right"
)
# "in" and "up" lexicalise into prenominal compounds ("logged in users",
# "set up reminders"), so they count as a complement only when a preposition
# or determiner follows and forces the verbal reading ("Moved up to 5pm.").
_ELLIPTICAL_PARTICLE = "in|up"
_ELLIPTICAL_PARTICLE_TAIL = "to|for|from|by|until|till|at|on"

_FIRST_PERSON_CLAIM = (
    r"\b(?:i|we)(?:'ve|'d)?\b(?:\s+(?:%(fillers)s)\b){0,3}"
    r"\s+(?:%(verbs)s)\b"
)
_PASSIVE_CLAIM = (
    r"\b(?:is|are|was|were|has|have|had)\b(?:\s+been\b)?"
    r"(?:\s+(?:%(fillers)s)\b){0,2}\s+(?:%(verbs)s)\b"
)
_BARE_PARTICIPLE_CLAIM = r"^\W*(?:[a-z][a-z']*\W+){0,3}(?:%(verbs)s)\b\W*$"
_ELLIPTICAL_CLAIM = (
    _CLAUSE_HEAD
    + r"\W*(?:[a-z0-9][a-z0-9']*\W+){0,2}"
    + r"(?:%(verbs)s)\b"
    + r"(?:\W*$"
    + r"|\W+(?:" + _ELLIPTICAL_OBJECT + "|" + _ELLIPTICAL_ADJUNCT + r")\b"
    + r"|\W+(?:" + _ELLIPTICAL_PARTICLE + r")\W+"
    + r"(?:" + _ELLIPTICAL_OBJECT + "|" + _ELLIPTICAL_PARTICLE_TAIL + r")\b"
    + r"|\W+[a-z0-9][a-z0-9']*\W*(?::|$))"
)

_COMPLETION_ADVERB = re.compile(
    r"\b(?:already|successfully|done|complete|completed)\b"
    r"|\ball\s+set\b|\btaken\s+care\s+of\b|\bjust\s+now\b"
)

_NEGATION = re.compile(
    r"\b(?:not|never|no|none|nothing|nobody|neither|nor|cannot|without)\b"
    r"|n't\b"
)
_PROSPECTIVE = re.compile(
    r"\b(?:can|could|may|might|will|would|shall|should|must|let|going|about|"
    r"plan|planning|intend|want|wants|prefer|if|whether|unless|once)\b"
    r"|'ll\b"
)
_INTERROGATIVE_OPENER = re.compile(
    r"^\W*(?:do|does|did|should|shall|would|could|can|will|am|are|is|was|"
    r"were|have|has|had|may|might|who|what|when|where|why|how|which)\b"
)
_DISTANCING = re.compile(
    r"\b(?:before|previously|earlier|originally|initially|historically)\b"
    r"|\bin\s+the\s+past\b|\byesterday\b"
    r"|\blast\s+(?:time|night|week|month|year)\b"
    r"|\b(?:always|usually|often|frequently|regularly|typically|generally|"
    r"sometimes|whenever)\b"
    r"|\b(?:every|each)\s+time\b"
    r"|\bfor\s+(?:other|another|others|someone|somebody|different)\b"
    r"|\b(?:many|several|multiple|numerous|various|countless)\s+[a-z]+s\b"
    r"|\b(?:dozens|hundreds|thousands|lots|plenty)\s+of\b"
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|[\r\n]+")
_WORD = re.compile(r"[a-z']+")

# Typographic punctuation, folded to its ASCII equivalent on the analysis
# copy only, so contractions and dash-joined clauses are recognised whichever
# form the model emits. Written as code points to keep this source ASCII.
_ANALYSIS_FOLDS = (
    (chr(0x2019), "'"),
    (chr(0x2018), "'"),
    (chr(0x2014), " - "),
    (chr(0x2013), " - "),
)

# Blocker scope, delimited by clause punctuation rather than by a count of
# words. _CLAUSE_SCAN_CHARS is a work bound per verb occurrence and not part
# of the scope model: it keeps matching linear on pathological input, and no
# clause of a spoken reply comes near it.
_CLAUSE_SCAN_CHARS = 400
_CLAUSE_BREAK = re.compile(r"[,;:]|\s-+\s")

# Words that cannot close a clause. A segment ending on one has opened a
# predicate that must continue, so it is still part of the next clause.
_DANGLING_TAIL = re.compile(
    r"(?:\b(?:am|is|are|was|were|be|been|being|has|have|had|do|does|did|"
    r"can|could|may|might|will|would|shall|should|must|not|never|no|nor|"
    r"neither|and|but|or|so|yet|plus|then|to|of|for|with|by|from|as|at|"
    r"in|on|than|that|which|because|while|since|though|although|if|"
    r"whether|unless|until)|n't)[^a-z0-9']*$"
)

# Finite auxiliary forms. A segment holding nothing else has no subject of
# its own, so a parenthetical cut this clause and it began before the break.
# Adverbs and coordinators are deliberately absent: they can head a clause
# whose subject really was dropped ("No problem, just added it.").
_SUBJECTLESS_WORDS = frozenset(
    "am is are was were be been being has have had do does did".split()
)

# Deterministic replacements. Each states the proposal without asserting any
# completed mutation, reads as one utterance for text to speech, and is itself
# blocked by the negation rule above, so re-running the guard over it is a
# no-op.
_SAFE_REPLIES = {
    "add_task": (
        "I have not added that yet, but I can add it to your list if you "
        "would like."
    ),
    "reschedule_task": (
        "I have not moved anything yet, but I can request that new time if "
        "you would like."
    ),
    "snooze_reminder": (
        "I have not snoozed that reminder yet, but I can snooze it if you "
        "would like."
    ),
    "dismiss_reminder": (
        "I have not dismissed that reminder yet, but I can dismiss it if "
        "you would like."
    ),
}


def _compile_mutation_rules() -> dict[str, tuple]:
    """Build the verb matcher and claim-signal matchers for each intent."""
    rules = {}
    for intent, verb_forms in _MUTATION_VERB_FORMS.items():
        fields = {"verbs": "|".join(verb_forms), "fillers": _CLAIM_FILLERS}
        rules[intent] = (
            re.compile(r"\b(?:%(verbs)s)\b" % fields),
            (
                re.compile(_FIRST_PERSON_CLAIM % fields),
                re.compile(_PASSIVE_CLAIM % fields),
                re.compile(_BARE_PARTICIPLE_CLAIM % fields),
                re.compile(_ELLIPTICAL_CLAIM % fields),
            ),
        )
    return rules


_MUTATION_RULES = _compile_mutation_rules()


def _reject_unexecuted_mutation_claim(intent: str, response_text: str) -> str:
    """Degrade unsafe mutation claims instead of crashing the graph.

    The text is returned byte-for-byte unless the intent is one of the
    mutation intents and some sentence asserts that the mutation already
    happened; in that case the whole draft is replaced by a deterministic
    prospective reply, so no completed claim survives anywhere in the output.
    Never raises for any input.
    """
    if not isinstance(intent, str) or not isinstance(response_text, str):
        return response_text
    rules = _MUTATION_RULES.get(intent)
    if rules is None:
        return response_text

    verb_pattern, claim_patterns = rules
    normalized = response_text
    for source, replacement in _ANALYSIS_FOLDS:
        normalized = normalized.replace(source, replacement)
    normalized = normalized.casefold()
    for raw_sentence in _SENTENCE_SPLIT.split(normalized):
        sentence = raw_sentence.strip()
        if sentence and _claims_completed_mutation(
            sentence, verb_pattern, claim_patterns
        ):
            return _SAFE_REPLIES[intent]
    return response_text


def _claims_completed_mutation(
    sentence: str,
    verb_pattern: re.Pattern,
    claim_patterns: tuple,
) -> bool:
    """Report whether one sentence asserts a completed mutation."""
    if verb_pattern.search(sentence) is None:
        return False
    if sentence.endswith("?") or _INTERROGATIVE_OPENER.match(sentence):
        return False
    if _DISTANCING.search(sentence):
        return False
    if not any(
        _leaves_claim_standing(sentence[: match.start()])
        for match in verb_pattern.finditer(sentence)
    ):
        return False
    if _COMPLETION_ADVERB.search(sentence):
        return True
    return any(pattern.search(sentence) for pattern in claim_patterns)


def _leaves_claim_standing(prefix: str) -> bool:
    """Report whether the verb's own clause leaves the claim standing."""
    scanned = prefix[-_CLAUSE_SCAN_CHARS:]
    if len(prefix) > _CLAUSE_SCAN_CHARS:
        scanned = scanned.partition(" ")[2]
    segments = _CLAUSE_BREAK.split(scanned)
    clause = segments[-1]
    earlier = segments[:-1]
    clause_words = _WORD.findall(clause)
    if clause_words and all(
        word in _SUBJECTLESS_WORDS for word in clause_words
    ):
        scope = earlier + [clause]
    else:
        scope = [
            segment for segment in earlier if _DANGLING_TAIL.search(segment)
        ]
        scope.append(clause)
    window = " ".join(scope)
    return not (_NEGATION.search(window) or _PROSPECTIVE.search(window))
# AI-BLOCK-END


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
