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

    monkeypatch.setattr(
        "adapters.llm.intent_classifier.requests.post", fake_post)
    classifier = OllamaIntentClassifier(settings=test_settings)
    classifier.classify("what should I focus on today?")

    assert captured["kwargs"]["json"]["keep_alive"] == "10m"
    assert captured["kwargs"]["json"]["options"]["num_predict"] == 40
    # test_settings sets intent_timeout_s=1.0, distinct from reasoning_timeout_s.
    assert captured["kwargs"]["timeout"] == 1.0


def test_intent_json_parser_accepts_valid_payload():
    """Verify that intent json parser accepts valid payload."""
    value = OllamaIntentClassifier._parse_json(
        '{"intent":"ask_status","confidence":0.9,"slots":{}}')
    assert value["intent"] == "ask_status"


def test_intent_json_parser_rejects_non_object():
    """Verify that intent json parser rejects non object."""
    try:
        OllamaIntentClassifier._parse_json('[1,2,3]')
    except IntentClassifierError:
        return
    raise AssertionError("Expected IntentClassifierError")


def _classify_with_payload(monkeypatch, test_settings, payload_json: str):
    """Run classify() against a canned Ollama response body."""
    def fake_post(url, **kwargs):
        return FakeResponse({"response": payload_json})

    monkeypatch.setattr(
        "adapters.llm.intent_classifier.requests.post", fake_post)
    classifier = OllamaIntentClassifier(settings=test_settings)
    return classifier.classify("irrelevant transcript")


def test_add_task_accepts_full_slots(monkeypatch, test_settings):
    """add_task with title, deadline, notes, and priority all parses through."""
    payload = (
        '{"intent":"add_task","confidence":0.9,"slots":'
        '{"title":"buy milk","deadline":"2026-09-24T09:00:00","notes":"2%","priority":"high"}}'
    )
    intent, _, slots = _classify_with_payload(
        monkeypatch, test_settings, payload)
    assert intent == "add_task"
    assert slots["title"] == "buy milk"
    assert slots["priority"] == "high"


def test_add_task_accepts_title_only(monkeypatch, test_settings):
    """add_task's deadline/notes/priority are optional -- title alone is valid."""
    payload = '{"intent":"add_task","confidence":0.9,"slots":{"title":"buy milk"}}'
    intent, _, slots = _classify_with_payload(
        monkeypatch, test_settings, payload)
    assert intent == "add_task"
    assert slots == {"title": "buy milk"}


def test_add_task_rejects_missing_title(monkeypatch, test_settings):
    """add_task without a title is a classifier contract violation."""
    payload = '{"intent":"add_task","confidence":0.9,"slots":{}}'
    try:
        _classify_with_payload(monkeypatch, test_settings, payload)
    except IntentClassifierError:
        return
    raise AssertionError("Expected IntentClassifierError")


def test_add_task_rejects_blank_title(monkeypatch, test_settings):
    """A whitespace-only title is treated the same as a missing one."""
    payload = '{"intent":"add_task","confidence":0.9,"slots":{"title":"   "}}'
    try:
        _classify_with_payload(monkeypatch, test_settings, payload)
    except IntentClassifierError:
        return
    raise AssertionError("Expected IntentClassifierError")


def test_add_task_rejects_invalid_priority(monkeypatch, test_settings):
    """priority is closed to low/normal/high."""
    payload = '{"intent":"add_task","confidence":0.9,"slots":{"title":"buy milk","priority":"urgent"}}'
    try:
        _classify_with_payload(monkeypatch, test_settings, payload)
    except IntentClassifierError:
        return
    raise AssertionError("Expected IntentClassifierError")


def test_reschedule_task_accepts_reference_and_deadline(monkeypatch, test_settings):
    """reschedule_task carries raw task_reference text, not a resolved task_id."""
    payload = (
        '{"intent":"reschedule_task","confidence":0.9,"slots":'
        '{"task_reference":"the dentist appointment","new_deadline":"tomorrow at 9am"}}'
    )
    intent, _, slots = _classify_with_payload(
        monkeypatch, test_settings, payload)
    assert intent == "reschedule_task"
    assert slots["task_reference"] == "the dentist appointment"
    assert slots["new_deadline"] == "tomorrow at 9am"


def test_reschedule_task_rejects_missing_task_reference(monkeypatch, test_settings):
    """reschedule_task without a task_reference is invalid -- no fallback guess."""
    payload = '{"intent":"reschedule_task","confidence":0.9,"slots":{"new_deadline":"tomorrow at 9am"}}'
    try:
        _classify_with_payload(monkeypatch, test_settings, payload)
    except IntentClassifierError:
        return
    raise AssertionError("Expected IntentClassifierError")


def test_reschedule_task_rejects_missing_new_deadline(monkeypatch, test_settings):
    """reschedule_task without a new_deadline is invalid."""
    payload = '{"intent":"reschedule_task","confidence":0.9,"slots":{"task_reference":"the dentist appointment"}}'
    try:
        _classify_with_payload(monkeypatch, test_settings, payload)
    except IntentClassifierError:
        return
    raise AssertionError("Expected IntentClassifierError")
