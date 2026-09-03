from pipeline.nodes.policy import apply_policy, make_policy_node


def test_production_policy_has_exact_five_rules():
    assert apply_policy("Low", "not_imminent") == "R1"
    assert apply_policy("Low", "imminent") == "R1"
    assert apply_policy("Moderate", "not_imminent") == "R2"
    assert apply_policy("Moderate", "imminent") == "R3"
    assert apply_policy("High", "not_imminent") == "R4"
    assert apply_policy("High", "imminent") == "R5"


def test_non_policy_interactions_are_n_a():
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
    class Store:
        def __init__(self):
            self.calls = []
        def suppress_pending_reminder_traces(self, user_id):
            self.calls.append(user_id)
            return 2
        def get_lead_time(self, user_id, default):
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
