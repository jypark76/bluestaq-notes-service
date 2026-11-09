from fastapi.testclient import TestClient

from src.main import create_app


def test_health_returns_ok():
    """The service starts and answers the health check."""
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
