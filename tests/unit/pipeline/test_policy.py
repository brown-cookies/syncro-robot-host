import pytest

from pipeline.nodes.policy import (
    NON_POLICY_INTENTS,
    POLICY_GOVERNED_INTENTS,
    apply_policy,
    clamp_lead_time,
    make_policy_node,
)


def test_production_policy_has_exact_five_rules():
    """The production reminder policy exposes exactly R1-R5."""
    assert apply_policy("Low", "not_imminent") == "R1"
    assert apply_policy("Low", "imminent") == "R1"
    assert apply_policy("Moderate", "not_imminent") == "R2"
    assert apply_policy("Moderate", "imminent") == "R3"
    assert apply_policy("High", "not_imminent") == "R4"
    assert apply_policy("High", "imminent") == "R5"


def test_policy_governed_intents_regression():
    """Reminder mutation intents remain in the R1-R5 policy domain."""
    assert POLICY_GOVERNED_INTENTS == frozenset({
        "dismiss_reminder",
        "snooze_reminder",
    })


def test_non_policy_intents_are_documented_separately():
    """Status and summary interactions remain explicitly outside R1-R5."""
    assert NON_POLICY_INTENTS == frozenset({
        "ask_status",
        "request_summary",
    })


@pytest.mark.parametrize(
    "intent",
    [
        "ask_status",
        "request_summary",
    ],
)
def test_non_policy_interactions_are_n_a(intent):
    """Non-policy conversational turns must not receive an R1-R5 decision."""
    node = make_policy_node(15, 15)

    result = node({
        "intent": intent,
        "affect_level": "High",
        "deadline_proximity": "imminent",
        "draft_response": "Status is ready.",
    })

    assert result.get("policy_rule") == "n/a"
    assert result.get("deadline_proximity") == "n/a"
    assert result.get("reminder_outcome") == "n/a"
    assert result.get("final_response") == "Status is ready."
    assert result.get("action_taken") == "deliver"


@pytest.mark.parametrize(
    "intent",
    [
        "snooze_reminder",
        "dismiss_reminder",
    ],
)
@pytest.mark.parametrize(
    ("affect", "proximity", "expected_rule", "expected_action"),
    [
        ("Low", "not_imminent", "R1", "deliver"),
        ("Low", "imminent", "R1", "deliver"),
        ("Moderate", "not_imminent", "R2", "defer"),
        ("Moderate", "imminent", "R3", "soften"),
        ("High", "not_imminent", "R4", "break_prompt"),
        ("High", "imminent", "R5", "deliver"),
    ],
)
def test_policy_governed_reminder_intents_route_to_r1_r5(
    intent,
    affect,
    proximity,
    expected_rule,
    expected_action,
):
    """
    Both live reminder mutation intents must remain connected to the
    production R1-R5 policy mapping.
    """
    node = make_policy_node(15, 15)

    result = node({
        "intent": intent,
        "user_id": "u1",
        "affect_level": affect,
        "deadline_proximity": proximity,
        "draft_response": "Reminder action ready.",
    })

    assert result.get("policy_rule") == expected_rule
    assert result.get("deadline_proximity") == proximity
    assert result.get("reminder_outcome") == "pending"
    assert result.get("action_taken") == expected_action


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5, 5),
        (15, 15),
        (60, 60),
        (0, 5),
        (-10, 5),
        (4.9, 5),
        (61, 60),
        (999, 60),
    ],
)
def test_lead_time_is_clamped_to_spec_range(raw, expected):
    """Verify that lead time is clamped to the 5-60 minute SPEC range."""
    assert clamp_lead_time(raw) == expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (3, 5.0),
        (15, 15.0),
        (90, 60.0),
    ],
)
def test_policy_node_traces_the_bounded_lead_time(stored, expected):
    """
    The value returned by the node, and therefore recorded in the trace,
    must always be bounded to the SPEC range.
    """

    class Store:
        def get_lead_time(self, user_id, default):
            """Return an out-of-range stored value on purpose."""
            return stored

    node = make_policy_node(15, 15, store=Store())

    result = node({
        "intent": "snooze_reminder",
        "user_id": "u1",
        "affect_level": "Moderate",
        "deadline_proximity": "not_imminent",
        "draft_response": "Please handle the slides.",
    })

    assert result.get("lead_time_min") == expected


def test_policy_node_r1_does_not_modify_draft():
    """R1 delivers the original draft unchanged."""
    node = make_policy_node(15, 15)

    result = node({
        "intent": "dismiss_reminder",
        "user_id": "u1",
        "affect_level": "Low",
        "deadline_proximity": "imminent",
        "draft_response": "Please handle the slides.",
    })

    assert result.get("policy_rule") == "R1"
    assert result.get("action_taken") == "deliver"
    assert result.get("final_response") == "Please handle the slides."
    assert result.get("reminder_outcome") == "pending"


def test_policy_node_r5_suppresses_pending_reminder_traces():
    """R5 performs the required pending-reminder suppression."""
    class Store:
        def __init__(self):
            self.suppressed_user_ids = []

        def get_lead_time(self, user_id, default):
            return default

        def suppress_pending_reminder_traces(self, user_id):
            self.suppressed_user_ids.append(user_id)

    store = Store()
    node = make_policy_node(15, 15, store=store)

    result = node({
        "intent": "dismiss_reminder",
        "user_id": "u1",
        "affect_level": "High",
        "deadline_proximity": "imminent",
        "draft_response": "I will handle it.",
    })

    assert result.get("policy_rule") == "R5"
    assert result.get("action_taken") == "deliver"
    assert result.get("reminder_outcome") == "pending"
    assert store.suppressed_user_ids == ["u1"]
