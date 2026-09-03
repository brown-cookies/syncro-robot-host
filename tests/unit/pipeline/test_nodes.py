import pytest

from pipeline.nodes.intent import make_intent_node
from pipeline.nodes.llm import _parse_json


class FakeClassifier:
    def __init__(self, result):
        self.result = result

    def classify(self, transcript):
        return self.result


def test_node1_intent_preserves_confidence_and_slots():
    node = make_intent_node(
        FakeClassifier(("snooze_reminder", 0.88, {"snooze_minutes": 5})),
        confidence_threshold=0.60,
    )
    result = node({"transcript": "snooze that for five minutes"})
    assert result["intent"] == "snooze_reminder"
    assert result["intent_confidence"] == 0.88
    assert result["slots"]["snooze_minutes"] == 5


def test_node1_low_confidence_routes_to_clarification():
    node = make_intent_node(FakeClassifier(("ask_status", 0.42, {})), 0.60)
    result = node({"transcript": "maybe something"})
    assert result["proposed_action"] == "clarify"
    assert "not confident" in result["final_response"].lower()


def test_node3_parser_accepts_fenced_json():
    parsed = _parse_json('```json\n{"response_text":"Done","proposed_action":"respond"}\n```')
    assert parsed["response_text"] == "Done"


def test_node3_parser_rejects_invalid_json():
    with pytest.raises(ValueError):
        _parse_json("not json")


def test_node3_rejects_unexecuted_mutation_claim():
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    with pytest.raises(ValueError, match="falsely claims a mutation"):
        _reject_unexecuted_mutation_claim(
            "add_task", "I've added the task to your schedule."
        )


def test_node3_allows_proposed_mutation_language():
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    text = _reject_unexecuted_mutation_claim(
        "add_task", "I can add that task for tomorrow at 9 p.m."
    )
    assert text.startswith("I can add")
