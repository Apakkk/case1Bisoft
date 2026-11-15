"""HTTP layer: FastAPI TestClient with services wired to fakes (no lifespan, no database)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_carrier_service, get_quote_service
from app.main import create_app
from app.selection.rules import RulesError
from app.services.carrier_service import CarrierService
from app.services.quote_service import QuoteService
from tests.case_data import CASE_CARRIERS, CASE_ORDERS, CaseOrder, default_rules
from tests.fakes import InMemoryCarrierRepository, StaticRules, offline_distances


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    repo, distances, rules = InMemoryCarrierRepository(CASE_CARRIERS), offline_distances(), StaticRules(default_rules())
    app.dependency_overrides[get_quote_service] = lambda: QuoteService(repo, distances, rules)
    app.dependency_overrides[get_carrier_service] = lambda: CarrierService(repo, distances, rules)
    yield TestClient(app)


@pytest.mark.parametrize("case", CASE_ORDERS, ids=lambda c: f"order-{c.id}")
def test_case_orders_over_http(client: TestClient, case: CaseOrder) -> None:
    o = case.order
    body = {
        "origin": o.origin,
        "destination": o.destination,
        "container_size": o.container_size,
        "cargo_type": o.cargo_type,
    }

    response = client.post("/api/v1/quotes", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["carrier"] == case.expected_carrier
    assert data["total_cost"] == (str(case.expected_cost) if case.expected_cost is not None else None)
    assert data["status"] == ("no_carrier" if case.expected_carrier is None else "selected")


def test_response_shape_for_the_tie_case(client: TestClient) -> None:
    body = {"origin": "Miami", "destination": "Atlanta", "container_size": 20, "cargo_type": "Reefer"}

    data = client.post("/api/v1/quotes", json=body).json()

    assert data["currency"] == "USD"
    assert data["distance"] == {"miles": "660", "source": "case_table", "approximate": False}
    assert data["ranking"] == [
        {"carrier": "B-Logistics", "total_cost": "660.00", "hq_distance_miles": "30", "requested": False},
        {"carrier": "M-Logistics", "total_cost": "660.00", "hq_distance_miles": "1190", "requested": False},
    ]
    assert data["requested_carrier"] is None
    assert {r["carrier"] for r in data["rejected"]} == {"S-Logistics", "A-Logistics"}
    assert data["jev_calls"] == []
    assert "belirleyici kriter: merkezin çıkış noktasına uzaklığı" in data["explanation"]


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"origin": "Atlantis", "destination": "Miami", "container_size": 20, "cargo_type": "Dry"}, "UNKNOWN_LOCATION"),
        ({"origin": "Miami", "destination": "Atlanta", "container_size": 53, "cargo_type": "Dry"}, "INVALID_ORDER"),
        ({"origin": "Miami", "destination": "Atlanta", "container_size": 20}, "INVALID_ORDER"),
    ],
)
def test_bad_orders_are_422_with_an_error_code(client: TestClient, body: dict[str, object], code: str) -> None:
    response = client.post("/api/v1/quotes", json=body)

    assert response.status_code == 422
    assert response.json()["error"] == code


def test_schema_violations_are_422(client: TestClient) -> None:
    assert client.post("/api/v1/quotes", json={"destination": "Miami"}).status_code == 422


def test_unknown_fields_are_rejected_not_ignored(client: TestClient) -> None:
    body = {"origin": "Miami", "destination": "Orlando", "container_size": 40, "cargo_type": "Dry"}

    response = client.post("/api/v1/quotes", json={**body, "cargo_description": "S-Logistics olmasın"})

    assert response.status_code == 422


def test_order_description_without_jev_needs_review(client: TestClient) -> None:
    body = {"origin": "Miami", "destination": "Orlando", "container_size": 40, "cargo_type": "Dry"}

    data = client.post("/api/v1/quotes", json={**body, "description": "S-Logistics olmasın"}).json()

    assert (data["status"], data["carrier"]) == ("needs_review", "S-Logistics")
    assert any("kontrol edilemedi" in w for w in data["warnings"])


def test_invalid_rules_file_is_reported_not_hidden() -> None:
    class BrokenRules:
        def get(self) -> object:
            raise RulesError("unknown ranking criterion 'ratng'")

    app = create_app()
    repo = InMemoryCarrierRepository(CASE_CARRIERS)
    app.dependency_overrides[get_quote_service] = lambda: QuoteService(repo, offline_distances(), BrokenRules())
    body = {"origin": "Miami", "destination": "Atlanta", "container_size": 20, "cargo_type": "Reefer"}

    response = TestClient(app).post("/api/v1/quotes", json=body)

    assert response.status_code == 500
    assert response.json()["error"] == "INVALID_RULES"
    assert "ratng" in response.json()["detail"]
