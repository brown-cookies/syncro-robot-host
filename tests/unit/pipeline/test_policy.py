from pipeline.nodes.policy import apply_policy, make_policy_node


def test_production_policy_has_exact_five_rules():
    """The pure reminder-delivery policy still exposes exactly R1-R5."""
    assert apply_policy("Low", "not_imminent") == "R1"
    assert apply_policy("Low", "imminent") == "R1"
    assert apply_policy("Moderate", "not_imminent") == "R2"
    assert apply_policy("Moderate", "imminent") == "R3"
    assert apply_policy("High", "not_imminent") == "R4"
    assert apply_policy("High", "imminent") == "R5"


def test_non_policy_interactions_are_n_a():
    """Conversational turns remain outside the reminder-delivery policy."""
    node = make_policy_node(15, 15)
    result = node({
        "intent": "ask_status",
        "affect_level": "High",
        "deadline_proximity": "imminent",
        "draft_response": "Status is ready.",
    })
    assert result["policy_rule"] == "n/a"
    assert result["deadline_proximity"] == "n/a"
    assert result["reminder_outcome"] == "n/a"
    assert result["final_response"] == "Status is ready."


import pytest


@pytest.mark.parametrize("intent", [
    "add_task",
    "reschedule_task",
    "snooze_reminder",
    "dismiss_reminder",
    "ask_status",
    "request_summary",
    "request_break",
])
def test_phase17_live_intents_are_outside_r1_r5_policy_domain(intent):
    node = make_policy_node(15, 15)
    result = node({
        "intent": intent,
        "user_id": "u1",
        "affect_level": "High",
        "deadline_proximity": "imminent",
        "draft_response": "The action is ready.",
    })
    assert result["policy_rule"] == "n/a"
    assert result["deadline_proximity"] == "n/a"
    assert result["reminder_outcome"] == "n/a"
    assert result["final_response"] == "The action is ready."
    assert result["action_taken"] == "deliver"


def test_non_policy_intents_are_documentation_metadata():
    from pipeline.nodes.policy import NON_POLICY_INTENTS, POLICY_GOVERNED_INTENTS

    assert NON_POLICY_INTENTS == frozenset({
        "ask_status",
        "request_summary",
        "request_break",
        "add_task",
        "reschedule_task",
        "snooze_reminder",
        "dismiss_reminder",
    })
    assert POLICY_GOVERNED_INTENTS == frozenset()
