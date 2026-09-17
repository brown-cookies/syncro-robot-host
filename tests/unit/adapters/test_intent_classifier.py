from adapters.llm.intent_classifier import IntentClassifierError, OllamaIntentClassifier


class FakeResponse:
    def __init__(self, payload):
        """Initialize the FakeResponse and establish its runtime state."""
        self._payload = payload

    def raise_for_status(self):
        """Provide the fake HTTP status-check behavior used by the test."""
        return None

    def json(self):
        """Return the fake JSON payload used by the test."""
        return self._payload


def test_intent_classifier_builds_bounded_request(monkeypatch, test_settings):
    """D5/Phase 9: intent classifier uses its own timeout, a bounded
    num_predict, and keep_alive -- independent of the reasoning adapter."""
    captured = {}

    def fake_post(url, **kwargs):
        """Provide a controlled HTTP response for the classifier test."""
        captured.update(url=url, kwargs=kwargs)
        return FakeResponse({"response": '{"intent":"ask_status","confidence":0.9,"slots":{}}'})

    monkeypatch.setattr("adapters.llm.intent_classifier.requests.post", fake_post)
    classifier = OllamaIntentClassifier(settings=test_settings)
    classifier.classify("what should I focus on today?")

    assert captured["kwargs"]["json"]["keep_alive"] == "10m"
    assert captured["kwargs"]["json"]["options"]["num_predict"] == 40
    # test_settings sets intent_timeout_s=1.0, distinct from reasoning_timeout_s.
    assert captured["kwargs"]["timeout"] == 1.0


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
