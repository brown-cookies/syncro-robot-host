"""Scope-freeze Item 3: POST /v1/tasks/ingest (SPEC 6.1a, verification 6a-6c).

Uses a fresh FastAPI app carrying only the tasks router and a real SQLite
store in a temp directory, so no models, Ollama, or audio hardware are needed.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.http import tasks
from storage.ingress import INGRESS_USER_ID
from storage.sqlite_store import SQLiteStore

SOURCE_TOKEN = "connector-token-abcdef123456"
OTHER_TOKEN = "other-connector-token-9876543"
PARTICIPANT_TOKEN = "participant-console-token-0001"  # a different scope: never a source token

URL = "/v1/tasks/ingest"


def _body(**overrides):
    body = {
        "source": "email-sim",
        "external_id": "msg-001",
        "title": "Send the weekly report",
        "due_at": "2026-10-01T09:00:00+08:00",
        "priority": "high",
        "created_at": "2026-09-24T08:00:00+08:00",
    }
    body.update(overrides)
    return body


def _auth(token=SOURCE_TOKEN):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(str(tmp_path / "ingest.db"))


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(tasks.router)
    app.state.ingest_deps = tasks.IngestDeps(
        store=store,
        source_tokens={"email-sim": SOURCE_TOKEN, "calendar-sim": OTHER_TOKEN},
    )
    return TestClient(app)


def test_valid_authenticated_request_creates_task_and_audit_row(client, store):
    response = client.post(URL, json=_body(), headers=_auth())

    assert response.status_code == 201
    data = response.json()
    assert data["source"] == "email-sim" and data["external_id"] == "msg-001"
    assert data["priority"] == "high" and data["status"] == "pending"

    tasks_table = store.list_tasks()
    assert len(tasks_table) == 1
    assert tasks_table[0]["title"] == "Send the weekly report"
    assert tasks_table[0]["user_id"] == INGRESS_USER_ID  # not a study participant

    events = store.list_ingress_events()
    assert [(e["source"], e["outcome"]) for e in events] == [("email-sim", "created")]


def test_same_source_and_external_id_is_idempotent(client, store):
    first = client.post(URL, json=_body(), headers=_auth())
    second = client.post(URL, json=_body(title="A changed title"), headers=_auth())

    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["task_id"] == first.json()["task_id"]
    assert len(store.list_tasks()) == 1                       # no duplicate row
    assert store.list_tasks()[0]["title"] == "Send the weekly report"  # no-op, not an update
    assert [e["outcome"] for e in store.list_ingress_events()] == ["created", "duplicate"]


def test_same_external_id_from_a_different_source_is_a_new_task(client, store):
    client.post(URL, json=_body(), headers=_auth())
    other = client.post(
        URL, json=_body(source="calendar-sim"), headers=_auth(OTHER_TOKEN)
    )
    assert other.status_code == 201
    assert len(store.list_tasks()) == 2


@pytest.mark.parametrize("headers", [
    {},                                             # missing
    {"Authorization": "Bearer wrong-token-value-1234567"},
    {"Authorization": "Basic abc"},                 # wrong scheme
    {"Authorization": "Bearer"},                    # no token
])
def test_missing_or_invalid_token_is_401_and_writes_nothing(client, store, headers):
    response = client.post(URL, json=_body(), headers=headers)
    assert response.status_code == 401
    assert store.list_tasks() == [] and store.list_ingress_events() == []


def test_participant_scope_token_is_rejected_on_ingest(client, store):
    """SPEC verification 6c / NFR-14: the two auth scopes are not interchangeable."""
    response = client.post(URL, json=_body(), headers=_auth(PARTICIPANT_TOKEN))
    assert response.status_code == 401
    assert store.list_tasks() == []


def test_valid_token_cannot_write_as_a_different_source(client, store):
    response = client.post(
        URL, json=_body(source="calendar-sim"), headers=_auth(SOURCE_TOKEN)
    )
    assert response.status_code == 401
    assert store.list_tasks() == []


def test_lowercase_bearer_scheme_is_accepted(client):
    response = client.post(
        URL, json=_body(), headers={"Authorization": f"bearer {SOURCE_TOKEN}"}
    )
    assert response.status_code == 201


def test_unknown_field_is_400_not_silently_ignored(client, store):
    """SPEC verification 6b."""
    response = client.post(URL, json=_body(surprise="x"), headers=_auth())
    assert response.status_code == 400
    assert "surprise" in response.json()["detail"]
    assert store.list_tasks() == []


def test_non_json_body_is_400(client):
    response = client.post(
        URL, content=b"not json", headers={**_auth(), "Content-Type": "application/json"}
    )
    assert response.status_code == 400


@pytest.mark.parametrize("bad", [
    {"title": ""},
    {"priority": "urgent"},
    {"created_at": "yesterday"},
    {"due_at": "not-a-date"},
    {"external_id": ""},
])
def test_invalid_field_values_are_422(client, store, bad):
    response = client.post(URL, json=_body(**bad), headers=_auth())
    assert response.status_code == 422
    assert store.list_tasks() == []


@pytest.mark.parametrize("missing", ["source", "external_id", "title", "created_at"])
def test_missing_required_field_is_422(client, missing):
    body = _body()
    del body[missing]
    assert client.post(URL, json=body, headers=_auth()).status_code == 422


def test_optional_fields_default(client, store):
    body = _body()
    del body["due_at"], body["priority"]
    response = client.post(URL, json=body, headers=_auth())
    assert response.status_code == 201
    assert response.json()["priority"] == "normal" and response.json()["due_at"] is None


def test_no_configured_tokens_fails_closed(store):
    app = FastAPI()
    app.include_router(tasks.router)
    app.state.ingest_deps = tasks.IngestDeps(store=store, source_tokens={})
    response = TestClient(app).post(URL, json=_body(), headers=_auth())
    assert response.status_code == 401


def test_unconfigured_app_returns_503():
    app = FastAPI()
    app.include_router(tasks.router)
    assert TestClient(app).post(URL, json=_body(), headers=_auth()).status_code == 503


def test_parse_source_tokens():
    assert tasks.parse_source_tokens("") == {}
    assert tasks.parse_source_tokens(
        f"email-sim:{SOURCE_TOKEN}, calendar-sim:{OTHER_TOKEN}"
    ) == {"email-sim": SOURCE_TOKEN, "calendar-sim": OTHER_TOKEN}
    with pytest.raises(ValueError):
        tasks.parse_source_tokens("email-sim:short")          # token too short
    with pytest.raises(ValueError):
        tasks.parse_source_tokens("no-separator-here")
    with pytest.raises(ValueError):
        tasks.parse_source_tokens(f"a:{SOURCE_TOKEN},a:{OTHER_TOKEN}")  # duplicate source


def test_ingest_tokens_setting_defaults_empty_and_reads_env(monkeypatch):
    from config.settings import Settings

    monkeypatch.delenv("INGEST_SOURCE_TOKENS", raising=False)
    assert Settings.from_env().ingest_source_tokens == ""
    monkeypatch.setenv("INGEST_SOURCE_TOKENS", f"email-sim:{SOURCE_TOKEN}")
    assert tasks.parse_source_tokens(Settings.from_env().ingest_source_tokens) == {
        "email-sim": SOURCE_TOKEN
    }
