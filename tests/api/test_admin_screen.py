"""Admin screen (Jinja2 + HTMX) over TestClient with fakes: pages render, forms validate, saves refresh rows."""

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_carrier_service, get_quote_service, get_rules
from app.main import create_app
from app.services.carrier_service import CarrierService
from app.services.quote_service import QuoteService
from tests.case_data import CASE_CARRIERS, default_rules
from tests.fakes import FakeJev, InMemoryCarrierRepository, StaticRules, offline_distances

VALID = {
    "name": "K-Logistics",
    "hq_city": "orlando",
    "rate_per_mile": "0.85",
    "min_miles": "",
    "max_miles": "500",
    "container_sizes": ["20", "40"],
    "cargo_types": ["Dry", "Reefer"],
    "description": "",
}


@dataclass
class Screen:
    client: TestClient
    repo: InMemoryCarrierRepository
    jev: FakeJev


@pytest.fixture
def screen() -> Iterator[Screen]:
    app = create_app()
    repo, jev = InMemoryCarrierRepository(CASE_CARRIERS), FakeJev(restriction=0.92)
    distances, rules = offline_distances(), StaticRules(default_rules())
    app.dependency_overrides[get_carrier_service] = lambda: CarrierService(repo, distances, rules, jev)
    app.dependency_overrides[get_quote_service] = lambda: QuoteService(repo, distances, rules, jev)
    app.dependency_overrides[get_rules] = lambda: rules.get()
    yield Screen(TestClient(app), repo, jev)


def test_list_page_shows_every_carrier(screen: Screen) -> None:
    html = screen.client.get("/admin/carriers").text

    for name in ("S-Logistics", "B-Logistics", "A-Logistics", "M-Logistics"):
        assert name in html
    assert "Sınırsız" in html  # M-Logistics has no distance limit
    assert "≤ 300 mil" in html and "≥ 250 mil" in html


def test_root_redirects_to_the_admin_screen(screen: Screen) -> None:
    response = screen.client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/carriers"


def test_static_assets_are_served_locally(screen: Screen) -> None:
    assert screen.client.get("/static/htmx.min.js").status_code == 200
    assert screen.client.get("/static/pico.min.css").status_code == 200


def test_new_form_offers_catalog_checkboxes(screen: Screen) -> None:
    html = screen.client.get("/admin/carriers/new").text

    assert 'hx-post="/admin/carriers"' in html
    for value in ('value="20"', 'value="45"', 'value="Hazardous"'):
        assert value in html


def test_create_refreshes_the_table_out_of_band(screen: Screen) -> None:
    html = screen.client.post("/admin/carriers", data=VALID).text

    assert "K-Logistics kaydedildi." in html
    assert 'id="carrier-rows" hx-swap-oob="true"' in html
    assert any(c.name == "K-Logistics" and c.hq_city == "Orlando" for c in screen.repo.list())


def test_description_is_prechecked_by_jev_and_shown_as_a_badge(screen: Screen) -> None:
    html = screen.client.post("/admin/carriers", data={**VALID, "description": "Hafta sonu çalışmıyoruz."}).text

    assert "Jev: açıklama kısıt içeriyor (olasılık 0.92)" in html
    assert "Kısıt içeriyor · 0.92" in html
    assert screen.jev.calls == ["note_has_restriction"]


def test_invalid_form_comes_back_with_turkish_field_errors(screen: Screen) -> None:
    bad = {**VALID, "rate_per_mile": "", "container_sizes": [], "min_miles": "600", "max_miles": "100"}

    html = screen.client.post("/admin/carriers", data=bad).text

    assert "Zorunlu alan." in html
    assert 'aria-invalid="true"' in html
    assert len(screen.repo.list()) == 4


def test_min_greater_than_max_is_explained(screen: Screen) -> None:
    html = screen.client.post("/admin/carriers", data={**VALID, "min_miles": "600", "max_miles": "100"}).text

    assert "Min mesafe, max mesafeden büyük olamaz." in html


def test_duplicate_name_is_a_field_error(screen: Screen) -> None:
    html = screen.client.post("/admin/carriers", data={**VALID, "name": "M-Logistics"}).text

    assert "Bu isimde bir firma zaten var." in html


def test_edit_form_is_prefilled_and_update_saves(screen: Screen) -> None:
    s_logistics = next(c for c in screen.repo.list() if c.name == "S-Logistics")

    form = screen.client.get(f"/admin/carriers/{s_logistics.id}/edit").text
    assert 'value="0.4"' in form and 'value="300"' in form and f'hx-put="/admin/carriers/{s_logistics.id}"' in form

    data = {**VALID, "name": "S-Logistics", "hq_city": "Tampa", "rate_per_mile": "0.45", "max_miles": "300"}
    html = screen.client.put(f"/admin/carriers/{s_logistics.id}", data=data).text

    assert "S-Logistics kaydedildi." in html
    updated = screen.repo.get(s_logistics.id or 0)
    assert updated is not None and str(updated.rate_per_mile) == "0.45"


def test_delete_removes_the_row(screen: Screen) -> None:
    carrier_id = screen.repo.list()[0].id

    response = screen.client.delete(f"/admin/carriers/{carrier_id}")

    assert (response.status_code, response.text) == (200, "")
    assert len(screen.repo.list()) == 3


def test_quote_form_shows_the_decision(screen: Screen) -> None:
    order = {"origin": "Miami", "destination": "Atlanta", "container_size": "20", "cargo_type": "Reefer"}

    html = screen.client.post("/admin/quote", data=order).text

    assert "B-Logistics" in html and "$660.00" in html
    assert "Seçildi" in html
    assert "Bu siparişte Jev çağrılmadı" in html


def test_quote_form_reports_unknown_cities(screen: Screen) -> None:
    order = {"origin": "Atlantis", "destination": "Miami", "container_size": "20", "cargo_type": "Dry"}

    html = screen.client.post("/admin/quote", data=order).text

    assert "UNKNOWN_LOCATION" in html and "Atlantis" in html
