from adapters.llm.intent_classifier import IntentClassifierError, OllamaIntentClassifier


def test_intent_json_parser_accepts_valid_payload():
    """Verify that intent json parser accepts valid payload."""
    value = OllamaIntentClassifier._parse_json('{"intent":"ask_status","confidence":0.9,"slots":{}}')
    assert value["intent"] == "ask_status"


def test_intent_json_parser_rejects_non_object():
    """Verify that intent json parser rejects non object."""
    try:
        OllamaIntentClassifier._parse_json('[1,2,3]')
    except IntentClassifierError:
        return
    raise AssertionError("Expected IntentClassifierError")
