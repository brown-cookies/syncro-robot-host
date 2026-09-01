from fastapi.testclient import TestClient

from api.app import app


def test_fastapi_application_starts() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_rejects_post() -> None:
    client = TestClient(app)
    assert client.post("/health").status_code == 405
