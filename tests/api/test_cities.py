"""City suggestions over HTTP: JSON API, the HTML list under the inputs, and the inputs on both forms."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.clients.distance.cities import load_city_directory
from app.clients.distance.static_table import load_static_table
from app.dependencies import get_carrier_service, get_city_service, get_rules
from app.main import create_app
from app.models.city import City
from app.services.carrier_service import CarrierService
from app.services.city_service import ONLINE_DISABLED, CityService
from tests.case_data import CASE_CARRIERS, default_rules
from tests.fakes import (
    FakeJev,
    FakePlaces,
    InMemoryCarrierRepository,
    InMemoryCityRepository,
    StaticRules,
    offline_distances,
)

TABLE = load_static_table(Path("config/distances.yaml"))
DIRECTORY = load_city_directory(Path("config/cities.csv"), Path("config/city_aliases.yaml"), TABLE.city_names())


@dataclass
class Api:
    client: TestClient
    places: FakePlaces
    cities: InMemoryCityRepository


def make_api(places: FakePlaces | None) -> Iterator[Api]:
    app = create_app()
    repo = InMemoryCityRepository()
    fake = places if places is not None else FakePlaces()
    service = CityService(DIRECTORY, repo, places)
    rules = StaticRules(default_rules())
    carriers = CarrierService(InMemoryCarrierRepository(CASE_CARRIERS), offline_distances(), rules, FakeJev())
    app.dependency_overrides[get_city_service] = lambda: service
    app.dependency_overrides[get_carrier_service] = lambda: carriers
    app.dependency_overrides[get_rules] = lambda: rules.get()
    yield Api(TestClient(app), fake, repo)


@pytest.fixture
def api() -> Iterator[Api]:
    yield from make_api(FakePlaces([City("Orland Park", "IL", 41.63, -87.85), City("Boca Raton", "FL", 26.37, -80.13)]))


@pytest.fixture
def offline() -> Iterator[Api]:
    yield from make_api(None)


def test_json_suggestions_are_case_insensitive_and_say_where_they_came_from(api: Api) -> None:
    data = api.client.get("/api/v1/cities", params={"q": "ORL"}).json()

    assert data == {
        "items": [
            {"name": "Orlando", "state": "FL", "source": "catalog"},
            {"name": "Orland Park", "state": "IL", "source": "ors"},
            {"name": "New Orleans", "state": "LA", "source": "catalog"},
        ],
        "warnings": [],
    }
    assert api.places.calls == ["ORL"]


def test_json_limit_is_validated(api: Api) -> None:
    assert len(api.client.get("/api/v1/cities", params={"q": "s", "limit": 2}).json()["items"]) == 2
    assert api.client.get("/api/v1/cities", params={"q": "s", "limit": 0}).status_code == 422
    assert api.client.get("/api/v1/cities", params={"q": "s", "limit": 11}).status_code == 422


def test_json_without_a_query_is_empty(api: Api) -> None:
    assert api.client.get("/api/v1/cities").json() == {"items": [], "warnings": []}


def test_html_list_bolds_the_typed_letters_and_marks_ors_cities(api: Api) -> None:
    html = api.client.get("/admin/cities/suggest", params={"q": "orl"}).text

    assert html.count('role="option"') == 3
    assert 'data-value="Orlando"' in html
    assert "<strong>Orl</strong>ando" in html
    assert re.search(r'data-value="Orland Park".*?>ORS</span>', html, re.S)
    assert "Öneri yok" not in html


def test_html_list_says_so_when_nothing_matches(offline: Api) -> None:
    html = offline.client.get("/admin/cities/suggest", params={"q": "zzz"}).text

    assert 'role="option"' not in html
    assert "Öneri yok — yazdığınız şehir yine de kullanılabilir." in html
    assert ONLINE_DISABLED in html


def test_html_list_escapes_what_the_user_typed(offline: Api) -> None:
    html = offline.client.get("/admin/cities/suggest", params={"q": "<script>"}).text

    assert "<script>" not in html


def city_inputs(html: str) -> dict[str, str]:
    """name -> the full <input> tag, for inputs wired to the suggestion list."""
    return {
        re.search(r'name="([^"]+)"', tag).group(1): tag  # type: ignore[union-attr]
        for tag in re.findall(r"<input[^>]*data-city-suggest[^>]*>", html, re.S)
    }


def test_quote_form_has_suggestions_on_origin_and_destination(api: Api) -> None:
    inputs = city_inputs(api.client.get("/admin/quote").text)

    assert set(inputs) == {"origin", "destination"}
    for name, tag in inputs.items():
        assert 'role="combobox"' in tag and 'autocomplete="off"' in tag
        assert f'aria-controls="{name}-city-list"' in tag
    assert 'value="Miami"' in inputs["origin"] and 'value="Atlanta"' in inputs["destination"]


def test_carrier_forms_have_suggestions_on_the_hq_city(api: Api) -> None:
    new = city_inputs(api.client.get("/admin/carriers/new").text)
    edit = city_inputs(api.client.get("/admin/carriers/1/edit").text)

    assert set(new) == set(edit) == {"hq_city"}
    assert 'value=""' in new["hq_city"]
    assert re.search(r'value="[A-Z][a-z]+', edit["hq_city"])


def test_the_script_is_served_and_loaded_by_every_page(api: Api) -> None:
    assert api.client.get("/static/city-autocomplete.js").status_code == 200
    assert "city-autocomplete.js" in api.client.get("/admin/carriers").text
