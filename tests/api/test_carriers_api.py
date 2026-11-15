from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_carrier_service, get_quote_service
from app.main import create_app
from app.services.carrier_service import CarrierService
from app.services.quote_service import QuoteService
from tests.case_data import CASE_CARRIERS, default_rules
from tests.fakes import InMemoryCarrierRepository, StaticRules, offline_distances

NEW = {
    "name": "K-Logistics",
    "hq_city": "ft. lauderdale",
    "min_miles": None,
    "max_miles": "500",
    "container_sizes": [20, 40],
    "cargo_types": ["dry", "Reefer"],
    "rate_per_mile": "0.85",
    "description": "",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    repo, distances, rules = InMemoryCarrierRepository(CASE_CARRIERS), offline_distances(), StaticRules(default_rules())
    app.dependency_overrides[get_carrier_service] = lambda: CarrierService(repo, distances, rules)
    app.dependency_overrides[get_quote_service] = lambda: QuoteService(repo, distances, rules)
    yield TestClient(app)


def test_list_returns_the_case_carriers(client: TestClient) -> None:
    names = [c["name"] for c in client.get("/api/v1/carriers").json()]

    assert names == ["A-Logistics", "B-Logistics", "M-Logistics", "S-Logistics"]


def test_create_normalizes_and_is_used_by_the_next_quote(client: TestClient) -> None:
    created = client.post("/api/v1/carriers", json=NEW)

    assert created.status_code == 201
    body = created.json()
    assert (body["hq_city"], body["cargo_types"], body["rate_per_mile"]) == (
        "Fort Lauderdale",
        ["Dry", "Reefer"],
        "0.85",
    )
    assert body["note_status"] == "none"

    quote = {"origin": "Miami", "destination": "Orlando", "container_size": 40, "cargo_type": "Reefer"}
    assert client.post("/api/v1/quotes", json=quote).json()["carrier"] == "K-Logistics"  # $199.75 < M's $235


def test_update_and_delete(client: TestClient) -> None:
    carrier_id = client.post("/api/v1/carriers", json=NEW).json()["id"]

    updated = client.put(f"/api/v1/carriers/{carrier_id}", json={**NEW, "rate_per_mile": "2.5"})
    assert updated.json()["rate_per_mile"] == "2.5"

    assert client.delete(f"/api/v1/carriers/{carrier_id}").status_code == 204
    assert client.get(f"/api/v1/carriers/{carrier_id}").status_code == 404


def test_duplicate_name_is_409(client: TestClient) -> None:
    response = client.post("/api/v1/carriers", json={**NEW, "name": "m-logistics"})

    assert response.status_code == 409
    assert response.json()["error"] == "DUPLICATE_CARRIER"


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"cargo_types": ["Flatrack"]}, "cargo_types"),
        ({"container_sizes": [53]}, "container_sizes"),
    ],
)
def test_catalog_violations_are_422_per_field(client: TestClient, change: dict[str, object], field: str) -> None:
    response = client.post("/api/v1/carriers", json={**NEW, **change})

    assert response.status_code == 422
    assert field in response.json()["detail"]


@pytest.mark.parametrize(
    "change",
    [{"min_miles": "600", "max_miles": "100"}, {"rate_per_mile": "0"}, {"container_sizes": []}, {"name": "  "}],
)
def test_schema_violations_are_422(client: TestClient, change: dict[str, object]) -> None:
    assert client.post("/api/v1/carriers", json={**NEW, **change}).status_code == 422


def test_unknown_carrier_is_404(client: TestClient) -> None:
    assert client.put("/api/v1/carriers/999", json=NEW).status_code == 404
    assert client.delete("/api/v1/carriers/999").status_code == 404
