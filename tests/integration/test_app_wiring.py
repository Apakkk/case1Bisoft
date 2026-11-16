"""The real app: lifespan, connection pool, PostgreSQL repositories and rules file (external APIs disabled)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from tests.case_data import CASE_ORDERS, CaseOrder
from tests.clients import logged_in

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    # Ignore .env entirely and disable both external APIs: no routing quota, no Jev tokens.
    offline = Settings(
        _env_file=None, database_url=get_settings().database_url, ors_api_key=None, typesafe_api_key=None
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.main.get_settings", lambda: offline)
        with logged_in(create_app()) as test_client:
            yield test_client


def test_health_reports_database_ok(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


@pytest.mark.parametrize("case", CASE_ORDERS, ids=lambda c: f"order-{c.id}")
def test_case_orders_end_to_end(client: TestClient, case: CaseOrder) -> None:
    o = case.order
    body = {
        "origin": o.origin,
        "destination": o.destination,
        "container_size": o.container_size,
        "cargo_type": o.cargo_type,
    }

    data = client.post("/api/v1/quotes", json=body).json()

    assert data["carrier"] == case.expected_carrier
    assert data["total_cost"] == (str(case.expected_cost) if case.expected_cost is not None else None)
