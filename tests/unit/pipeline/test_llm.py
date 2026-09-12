import pytest

from pipeline.nodes.llm import _reject_unexecuted_mutation_claim, make_llm_node


class CaptureLLM:
    def __init__(self, response='{"response_text":"You have one overdue task.","proposed_action":"deliver"}'):
        """Initialize the CaptureLLM and establish its runtime state."""
        self.prompt = None
        self.response = response

    def generate(self, prompt):
        """Generate an LLM response from the supplied conversation state and context."""
        self.prompt = prompt
        return self.response


# AI-BLOCK-START:mutation-claim-cases
# Canonical phrasing table for the mutation-claim guard: each row is an
# (intent, drafted response) pair. The first table is the safety boundary -
# every row asserts a mutation that no executor performed, so the guard must
# replace it. The second table is the false-positive boundary - every row is
# ordinary wording (denial, proposal, question, incidental or out-of-turn use
# of the same verb, or a non-mutation intent), so the guard must return it
# byte-for-byte.
DEGRADED_MUTATION_CLAIM_CASES = (
    # first-person past assertions
    ("add_task", "I added it to your list."),
    ("snooze_reminder", "I snoozed the reminder for you."),
    ("reschedule_task", "I moved the meeting to 5pm."),
    # first-person perfect assertions, with and without contraction
    ("add_task", "I have added it."),
    ("dismiss_reminder", "I've dismissed it."),
    ("dismiss_reminder", "I already dismissed it."),
    # agentless passive completions
    ("add_task", "Task added."),
    ("dismiss_reminder", "Reminder dismissed."),
    ("dismiss_reminder", "Nevermind, this has been cleared."),
    # completion adverb, no terminal punctuation
    ("add_task", "Task successfully created"),
    # multi-sentence: a safe sentence followed by an unsafe one
    ("add_task", "I can do that. Task added."),
    # mixed case and surrounding whitespace
    ("snooze_reminder", "  Okay, I SNOOZED it for you  "),
    # subject dropped: the clause opens on the completed verb itself
    ("add_task", "Added the task to your list."),
    ("add_task", "Added it."),
    ("dismiss_reminder", "Cancelled the reminder for you."),
    ("reschedule_task", "Moved the meeting to 5pm."),
    ("snooze_reminder", "Snoozed it for an hour."),
    ("dismiss_reminder", "Cleared that for you."),
    ("snooze_reminder", "Pushed it back to seven."),
    ("dismiss_reminder", "Removed it from your reminders."),
    # subject dropped after a discourse marker or coordinator
    ("add_task", "Okay, created the task for 9pm."),
    ("reschedule_task", "Went ahead and moved it to 5pm."),
    ("add_task", "Done. Added it to your list."),
    # auxiliary elided: subject noun, participle, then an adjunct
    ("add_task", "Task added to your list."),
    ("dismiss_reminder", "Reminder cleared for you."),
    ("dismiss_reminder", "It's cleared now."),
    # subject dropped with a colon or a particle complement
    ("add_task", "Added task: buy milk."),
    ("reschedule_task", "Moved up to 5pm."),
    # a discourse marker or interjection sits outside the clause that
    # carries the verb, so it cannot block the claim it introduces - not
    # even when the marker itself contains a negator
    ("reschedule_task", "No problem, moved the meeting to 4pm."),
    ("dismiss_reminder", "No worries, cleared it for you."),
    ("add_task", "No trouble, added it to your list."),
    ("snooze_reminder", "No issue, snoozed it for an hour."),
    ("dismiss_reminder", "No rush, dismissed that one."),
    ("add_task", "Not a problem, logged the task for you."),
    ("reschedule_task", "Not a problem - updated the time to 6pm."),
    ("add_task", "Sure, added it to your list."),
    ("snooze_reminder", "Of course, snoozed it for an hour."),
    ("dismiss_reminder", "Right, closed the reminder for you."),
    ("reschedule_task", "Alright, rescheduled it for Friday."),
    ("add_task", "Done - saved the task for tomorrow."),
    ("snooze_reminder", "No problem, just snoozed it for an hour."),
    ("dismiss_reminder", "No worries at all - cleared it for you."),
)

UNCHANGED_MUTATION_RESPONSE_CASES = (
    # denial / negation
    ("dismiss_reminder", "I have not cleared anything yet."),
    ("snooze_reminder", "Nothing was postponed."),
    ("add_task", "I haven't added it yet."),
    ("reschedule_task", "It was not rescheduled."),
    ("dismiss_reminder", "Nothing has been dismissed."),
    # prospective / offer
    ("add_task", "I can add that."),
    ("add_task", "Let me add that."),
    ("add_task", "I am going to add it."),
    ("add_task", "I will add that to your list."),
    ("snooze_reminder", "I can snooze it for you."),
    ("add_task", "I would have added it if you had confirmed."),
    # questions, including subject-dropped ones
    ("snooze_reminder", "Should I snooze it?"),
    ("add_task", "Do you want me to add it?"),
    ("dismiss_reminder", "Should I dismiss the reminder?"),
    ("reschedule_task", "Moved to 5pm?"),
    ("snooze_reminder", "Snoozed until when?"),
    ("add_task", "Added to tomorrow instead?"),
    # incidental or out-of-turn use of the verb
    ("add_task", "I have your address on file."),
    ("add_task", "I have added many tasks before for other users."),
    # completed verb form read as an adjective, not as a claim
    ("add_task", "Added tasks appear at the top of your list."),
    ("dismiss_reminder", "Cleared reminders stay in your history."),
    ("reschedule_task", "Moved meetings keep their original reminders."),
    ("reschedule_task", "Your updated schedule shows 5pm."),
    ("add_task", "Logged in users see their own list."),
    # wording already exercised end to end
    ("dismiss_reminder", "I will keep the reminder focused."),
    # non-mutation intents are never evaluated
    ("request_summary", "I added it to your list."),
    ("ask_status", "Task added."),
    ("request_summary", "Added the task to your list."),
    # empty and whitespace-only text is returned as given, never rejected
    ("add_task", ""),
    ("add_task", "   "),
    # a determiner-negator heading the subject noun phrase governs the verb
    # of its own clause however long that noun phrase grows
    ("dismiss_reminder", "None of the reminders were dismissed."),
    ("add_task", "None of the tasks were added."),
    ("dismiss_reminder",
     "None of the recurring weekly reminders were dismissed."),
    ("reschedule_task",
     "None of the meetings on Thursday afternoon were moved."),
    ("snooze_reminder",
     "None of the reminders you set for this weekend were snoozed."),
    ("dismiss_reminder", "Neither reminder was cleared."),
    ("reschedule_task",
     "Neither of the two calendar entries was rescheduled."),
    ("add_task", "No tasks were added."),
    ("add_task", "No new tasks have been added to your shopping list."),
    ("snooze_reminder",
     "No reminders about the dentist appointment were delayed."),
    ("add_task", "No item from the list you dictated was saved."),
    # a parenthetical splits subject from predicate, or splits an auxiliary
    # from its participle; the clause is still one clause
    ("dismiss_reminder",
     "None of the reminders, including the weekly ones, were dismissed."),
    ("dismiss_reminder", "I have not, however, dismissed that reminder."),
    # a marker clause that carries its own blocker still blocks
    ("add_task", "No problem, I have not added it yet."),
    ("snooze_reminder", "Not a problem, I can snooze it for you."),
    ("dismiss_reminder",
     "No problem, cleared reminders stay in your history."),
)
# AI-BLOCK-END


def test_overdue_request_limits_llm_context_to_overdue_tasks():
    """Verify that overdue request limits llm context to overdue tasks."""
    llm = CaptureLLM()
    node = make_llm_node(llm)

    result = node({
        "transcript": "What is my overdue task?",
        "intent": "request_summary",
        "intent_confidence": 0.99,
        "slots": {},
        "context": {
            "tasks": [
                {"task_id": "t1", "title": "Future task", "status": "pending"},
            ],
            "overdue_tasks": [
                {"task_id": "t2", "title": "Overdue task", "status": "overdue"},
            ],
            "recent_routine": None,
        },
    })

    assert result["draft_response"] == "You have one overdue task."
    assert '"Overdue task"' in llm.prompt
    assert '"Future task"' not in llm.prompt
    assert "overdue_tasks" in llm.prompt


def _claim_fragment(response_text: str) -> str:
    """Normalise a drafted claim so it can be searched for in the output."""
    return response_text.strip().casefold().rstrip(".!?")


@pytest.mark.parametrize(
    ("intent", "response_text"), UNCHANGED_MUTATION_RESPONSE_CASES
)
def test_ordinary_wording_is_returned_unchanged(intent, response_text):
    result = _reject_unexecuted_mutation_claim(intent, response_text)

    assert result == response_text


@pytest.mark.parametrize(
    ("intent", "response_text"), DEGRADED_MUTATION_CLAIM_CASES
)
def test_completed_mutation_claim_is_replaced(intent, response_text):
    result = _reject_unexecuted_mutation_claim(intent, response_text)

    assert result != response_text
    assert result.strip()
    assert _claim_fragment(response_text) not in result.casefold()
    assert not result.endswith(response_text)


@pytest.mark.parametrize("response_text", ["", "   ", "\t\n "])
def test_blank_response_text_is_returned_without_raising(response_text):
    result = _reject_unexecuted_mutation_claim("add_task", response_text)

    assert result == response_text


@pytest.mark.parametrize("intent", ["request_summary", "ask_status"])
def test_non_mutation_intent_keeps_text_containing_a_mutation_verb(intent):
    response_text = "I already dismissed the reminder and added a task."

    result = _reject_unexecuted_mutation_claim(intent, response_text)

    assert result == response_text


def test_clarification_path_returns_before_the_mutation_guard():
    llm = CaptureLLM()
    node = make_llm_node(llm)
    final_response = "I added it to your list."

    result = node({
        "proposed_action": "clarify",
        "final_response": final_response,
        "intent": "add_task",
    })

    assert result["draft_response"] == final_response
    assert result["proposed_action"] == "clarify"
    assert llm.prompt is None
