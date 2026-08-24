from fastapi.testclient import TestClient

from bus.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app(bearer_token="test-bus-token"))

    assert client.get("/health").status_code == 401
    response = client.get("/health", headers={"Authorization": "Bearer test-bus-token"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
