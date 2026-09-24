from pipeline.nodes.policy import apply_policy, make_policy_node


def test_production_policy_has_exact_five_rules():
    """Verify that production policy has exact five rules."""
    assert apply_policy("Low", "not_imminent") == "R1"
    assert apply_policy("Low", "imminent") == "R1"
    assert apply_policy("Moderate", "not_imminent") == "R2"
    assert apply_policy("Moderate", "imminent") == "R3"
    assert apply_policy("High", "not_imminent") == "R4"
    assert apply_policy("High", "imminent") == "R5"


def test_non_policy_interactions_are_n_a():
    """Verify that non policy interactions are n a."""
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


def test_r2_defers_without_inflating_lead_time():
    """Verify that r2 defers without inflating lead time."""
    node = make_policy_node(15, 15)
    result = node({
        "intent": "snooze_reminder",
        "user_id": "u1",
        "affect_level": "Moderate",
        "deadline_proximity": "not_imminent",
        "draft_response": "Please handle the presentation slides.",
    })
    assert result["policy_rule"] == "R2"
    assert result["action_taken"] == "defer"
    assert result["lead_time_min"] == 15
    assert result["reminder_outcome"] == "pending"


def test_r3_softens_delivery():
    """Verify that r3 softens delivery."""
    node = make_policy_node(15, 15)
    result = node({
        "intent": "snooze_reminder",
        "user_id": "u1",
        "affect_level": "Moderate",
        "deadline_proximity": "imminent",
        "draft_response": "Please handle the presentation slides.",
    })
    assert result["policy_rule"] == "R3"
    assert result["action_taken"] == "soften"
    assert "time-sensitive" in result["final_response"]


def test_r4_adds_break_prompt_and_defer():
    """Verify that r4 adds break prompt and defer."""
    node = make_policy_node(15, 15)
    result = node({
        "intent": "dismiss_reminder",
        "user_id": "u1",
        "affect_level": "High",
        "deadline_proximity": "not_imminent",
        "draft_response": "Here is the reminder.",
    })
    assert result["policy_rule"] == "R4"
    assert result["action_taken"] == "break_prompt"
    assert "gently" in result["final_response"]


def test_r5_delivers_triggering_reminder():
    """Verify that r5 delivers triggering reminder."""
    class Store:
        def __init__(self):
            """Initialize the Store and establish its runtime state."""
            self.calls = []
        def suppress_pending_reminder_traces(self, user_id):
            """Suppress other pending reminder traces when policy requires it."""
            self.calls.append(user_id)
            return 2
        def get_lead_time(self, user_id, default):
            """Read the configured lead-time value used by policy evaluation."""
            return default

    store = Store()
    node = make_policy_node(15, 15, store=store)
    result = node({
        "intent": "dismiss_reminder",
        "user_id": "u1",
        "affect_level": "High",
        "deadline_proximity": "imminent",
        "draft_response": "Please focus on the top priority.",
    })
    assert result["policy_rule"] == "R5"
    assert result["action_taken"] == "deliver"
    assert result["reminder_outcome"] == "pending"
    assert store.calls == ["u1"]


import pytest

from pipeline.nodes.policy import clamp_lead_time


@pytest.mark.parametrize("raw, expected", [
    (5, 5), (15, 15), (60, 60),   # in range: unchanged
    (0, 5), (-10, 5), (4.9, 5),   # below range: clamp up
    (61, 60), (999, 60),          # above range: clamp down
])
def test_lead_time_is_clamped_to_spec_range(raw, expected):
    """Verify that lead time is clamped to the 5-60 minute SPEC range."""
    assert clamp_lead_time(raw) == expected


@pytest.mark.parametrize("stored, expected", [(3, 5.0), (15, 15.0), (90, 60.0)])
def test_policy_node_traces_the_bounded_lead_time(stored, expected):
    """The value in the node result (which becomes the trace) is the bounded one."""
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
    assert result["lead_time_min"] == expected


def test_all_five_rules_are_reachable_through_the_node():
    """Item 1 verification: each of R1-R5 can be provoked via the node."""
    cases = {
        ("Low", "not_imminent"): "R1",
        ("Moderate", "not_imminent"): "R2",
        ("Moderate", "imminent"): "R3",
        ("High", "not_imminent"): "R4",
        ("High", "imminent"): "R5",
    }
    node = make_policy_node(15, 15)
    for (affect, prox), rule in cases.items():
        result = node({
            "intent": "snooze_reminder", "user_id": "u1",
            "affect_level": affect, "deadline_proximity": prox,
            "draft_response": "Draft.",
        })
        assert result["policy_rule"] == rule
