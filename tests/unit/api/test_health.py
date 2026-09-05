from fastapi.testclient import TestClient

from api.app import app


def test_fastapi_application_starts() -> None:
    """Verify that fastapi application starts."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_rejects_post() -> None:
    """Verify that health endpoint rejects post."""
    client = TestClient(app)
    assert client.post("/health").status_code == 405
