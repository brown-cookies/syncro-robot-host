import pytest

from pipeline.nodes.intent import make_intent_node
from pipeline.nodes.llm import _parse_json


class FakeClassifier:
    def __init__(self, result):
        """Initialize the FakeClassifier and establish its runtime state."""
        self.result = result

    def classify(self, transcript):
        """Classify the supplied input using the configured classifier."""
        return self.result


def test_node1_intent_preserves_confidence_and_slots():
    """Verify that node1 intent preserves confidence and slots."""
    node = make_intent_node(
        FakeClassifier(("snooze_reminder", 0.88, {"snooze_minutes": 5})),
        confidence_threshold=0.60,
    )
    result = node({"transcript": "snooze that for five minutes"})
    assert result["intent"] == "snooze_reminder"
    assert result["intent_confidence"] == 0.88
    assert result["slots"]["snooze_minutes"] == 5


def test_node1_low_confidence_routes_to_clarification():
    """Verify that node1 low confidence routes to clarification."""
    node = make_intent_node(FakeClassifier(("ask_status", 0.42, {})), 0.60)
    result = node({"transcript": "maybe something"})
    assert result["proposed_action"] == "clarify"
    assert "not confident" in result["final_response"].lower()


def test_node3_parser_accepts_fenced_json():
    """Verify that node3 parser accepts fenced json."""
    parsed = _parse_json('```json\n{"response_text":"Done","proposed_action":"respond"}\n```')
    assert parsed["response_text"] == "Done"


def test_node3_parser_rejects_invalid_json():
    """Verify that node3 parser rejects invalid json."""
    with pytest.raises(ValueError):
        _parse_json("not json")


def test_node3_degrades_unexecuted_mutation_claim():
    """Verify that node3 degrades unexecuted mutation claim."""
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    result = _reject_unexecuted_mutation_claim(
        "add_task", "I've added the task to your schedule."
    )
    assert result.startswith("I can help with that")


def test_node3_allows_proposed_mutation_language():
    """Verify that node3 allows proposed mutation language."""
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    text = _reject_unexecuted_mutation_claim(
        "add_task", "I can add that task for tomorrow at 9 p.m."
    )
    assert text.startswith("I can add")


def test_node3_mutation_guard_uses_word_boundaries():
    """Verify that node3 mutation guard uses word boundaries."""
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    text = "I have your address on file, so where should I put this task?"
    assert _reject_unexecuted_mutation_claim("add_task", text) == text


def test_node3_mutation_guard_allows_explicit_denials():
    """Verify that node3 mutation guard allows explicit denials."""
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    for intent, text in (
        ("dismiss_reminder", "I have not cleared anything yet."),
        ("snooze_reminder", "Nothing was postponed. I have no pending items."),
    ):
        assert _reject_unexecuted_mutation_claim(intent, text) == text


def test_node3_mutation_guard_flags_affirmative_completion_beyond_i_have():
    """Verify that node3 mutation guard flags affirmative completion beyond i have."""
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    text = "The task was added successfully."
    result = _reject_unexecuted_mutation_claim("add_task", text)
    assert result.startswith("I can help with that")


def test_node3_mutation_guard_allows_prospective_successful_language():
    """Verify that node3 mutation guard allows prospective successful language."""
    from pipeline.nodes.llm import _reject_unexecuted_mutation_claim

    text = "I can add the task successfully once you confirm."
    assert _reject_unexecuted_mutation_claim("add_task", text) == text
