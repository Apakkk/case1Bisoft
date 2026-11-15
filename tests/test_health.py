import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_without_database_reports_unavailable() -> None:
    # No `with` block: the lifespan (and so the pool) is not started.
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "unavailable"}


@pytest.mark.db
def test_health_with_database() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.json() == {"status": "ok", "database": "ok"}
