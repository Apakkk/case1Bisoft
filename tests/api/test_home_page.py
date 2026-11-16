"""Home page showroom over TestClient with fakes: one truck per carrier, safe names, no paid calls."""

import json
import re
from collections.abc import Iterable
from dataclasses import replace

from fastapi.testclient import TestClient

from app.dependencies import get_carrier_service, get_rules
from app.main import create_app
from app.models.carrier import Carrier
from app.services.carrier_service import CarrierService
from tests.case_data import CASE_CARRIERS, S_LOGISTICS, default_rules
from tests.clients import logged_in
from tests.fakes import FakeJev, InMemoryCarrierRepository, StaticRules, offline_distances

DATA_BLOCK = re.compile(r'<script type="application/json" id="fleet-data">(.*?)</script>', re.S)


def client_with(carriers: Iterable[Carrier], jev: FakeJev | None = None) -> TestClient:
    app = create_app()
    repo, jev = InMemoryCarrierRepository(carriers), jev or FakeJev()
    distances, rules = offline_distances(), StaticRules(default_rules())
    app.dependency_overrides[get_carrier_service] = lambda: CarrierService(repo, distances, rules, jev)
    app.dependency_overrides[get_rules] = lambda: rules.get()
    return logged_in(app)


def page_data(html: str) -> dict[str, object]:
    match = DATA_BLOCK.search(html)
    assert match, "the page carries its JSON block"
    data: dict[str, object] = json.loads(match.group(1))
    return data


def test_home_page_shows_one_truck_per_carrier() -> None:
    response = client_with(CASE_CARRIERS).get("/")

    assert response.status_code == 200
    html = response.text
    assert html.count('aria-roledescription="slide"') == 4
    for name in ("S-Logistics", "B-Logistics", "A-Logistics", "M-Logistics"):
        assert re.search(rf'<span class="livery-name vinyl" style="--fs: \d+">{name}</span>', html), name  # trailer
        assert f"/ 4: {name}" in html  # the slide label
    carriers = page_data(html)["carriers"]
    assert isinstance(carriers, list)
    assert [c["name"] for c in carriers] == ["A-Logistics", "B-Logistics", "M-Logistics", "S-Logistics"]


def test_home_page_shows_real_carrier_facts() -> None:
    html = client_with([S_LOGISTICS]).get("/").text

    assert "Tampa merkezli · 40 ve 45 ft · Dry" in html
    assert "$0.40 / mil" in html
    assert "≤ 300 mil" in html


def test_every_truck_carries_the_four_facet_markings() -> None:
    html = client_with(CASE_CARRIERS).get("/").text

    for facet in ("rate", "distance", "equipment", "cargo"):
        assert html.count(f'data-decal="{facet}"') == 4, facet
    assert html.count('class="hazmat"') == 2  # A- and M-Logistics carry Hazardous
    assert '<span class="livery-size-value" style="--fs: ' in html and "40 · 45 FT</span>" in html  # S-Logistics
    assert "Tampa merkezli</span>" in html and "Mesafe ≤ 300 mil</span>" in html  # S-Logistics' cab door


def test_home_page_escapes_carrier_names() -> None:
    evil = replace(S_LOGISTICS, name="<script>alert(1)</script>")

    html = client_with([evil]).get("/").text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    block = DATA_BLOCK.search(html)
    assert block and "<script>" not in block.group(1) and "\\u003cscript\\u003e" in block.group(1)
    carriers = page_data(html)["carriers"]
    assert isinstance(carriers, list) and carriers[0]["name"] == "<script>alert(1)</script>"


def test_home_page_without_carriers_invites_adding_one() -> None:
    html = client_with([]).get("/").text

    assert "Henüz firma yok" in html
    assert '<a class="cta" href="/admin/carriers">Firma ekle</a>' in html
    assert 'aria-roledescription="slide"' not in html
    assert page_data(html)["carriers"] == []


def test_home_page_makes_no_jev_call() -> None:
    jev = FakeJev(restriction=0.92)
    noted = replace(S_LOGISTICS, description="Sadece hafta içi çalışır.")

    client_with([noted, *CASE_CARRIERS[1:]], jev).get("/")

    assert jev.calls == []


def test_home_page_assets_are_served_locally() -> None:
    client = client_with(CASE_CARRIERS)

    for path in ("home/home.css", "home/home.js", "home/truck.webp", "home/scene.jpg"):
        assert client.get(f"/static/{path}").status_code == 200, path
    assert "https://" not in re.sub(r"https?://testserver", "", client.get("/").text)


def test_admin_pages_link_back_to_the_home_page() -> None:
    html = client_with(CASE_CARRIERS).get("/admin/carriers").text

    assert '<a class="brand" href="/">' in html  # the same top bar as the showroom
    assert ">Filo</a>" not in html


def test_menus_have_no_api_tab() -> None:
    client = client_with(CASE_CARRIERS)

    for path in ("/", "/admin/carriers"):
        assert 'href="/docs"' not in client.get(path).text, path


def test_pages_share_the_showroom_top_bar_and_backdrop() -> None:
    client = client_with(CASE_CARRIERS)

    for path in ("/", "/admin/carriers", "/admin/quote"):
        html = client.get(path).text
        assert '<header class="topbar">' in html and "shell.css" in html, path
        assert "home/scene-blur.jpg" in html, path
    assert "stage-noise" not in client.get("/admin/carriers").text  # no moving background behind forms


def test_the_fleet_nav_only_says_scroll() -> None:
    html = client_with(CASE_CARRIERS).get("/").text

    assert '<p class="drag-hint">Kaydır</p>' in html and "Sürükle" not in html


def test_each_truck_has_its_name_for_the_page_address() -> None:
    carriers = page_data(client_with(CASE_CARRIERS).get("/").text)["carriers"]

    assert isinstance(carriers, list)
    assert [c["slug"] for c in carriers] == ["a-logistics", "b-logistics", "m-logistics", "s-logistics"]
