"""Admin rules page over TestClient: the ranking is edited on screen and written to a copy of rules.yaml."""

import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_quote_service, get_rules, get_rules_service
from app.main import create_app
from app.models.carrier import Carrier
from app.repositories.rules_repository import FileRulesRepository
from app.services.quote_service import QuoteService
from app.services.rules_service import RulesService
from tests.case_data import CASE_CARRIERS
from tests.clients import logged_in
from tests.fakes import InMemoryCarrierRepository, offline_distances

# Miami-based and expensive: wins only when HQ proximity outranks price.
X_LOGISTICS = Carrier("X-Logistics", "Miami", None, None, frozenset({40}), frozenset({"Dry"}), Decimal("3.00"))
ORDER = {"origin": "Miami", "destination": "Orlando", "container_size": 40, "cargo_type": "Dry"}


@dataclass
class Screen:
    client: TestClient
    path: Path


@pytest.fixture
def screen(tmp_path: Path) -> Iterator[Screen]:
    path = tmp_path / "rules.yaml"
    shutil.copy("config/rules.yaml", path)
    store = FileRulesRepository(path)
    repo = InMemoryCarrierRepository((*CASE_CARRIERS, X_LOGISTICS))
    app = create_app()
    app.dependency_overrides[get_rules_service] = lambda: RulesService(store)
    app.dependency_overrides[get_rules] = lambda: store.get()
    app.dependency_overrides[get_quote_service] = lambda: QuoteService(repo, offline_distances(), store)
    yield Screen(logged_in(app), path)


def order_of(html: str) -> list[str]:
    return re.findall(r'name="ranking" value="([a-z_]+)"', html)


def test_page_shows_the_current_order_and_the_fixed_tie_breaker(screen: Screen) -> None:
    html = screen.client.get("/admin/rules").text

    assert order_of(html) == ["total_cost", "hq_proximity"]  # a requested carrier is not a rule
    assert "Sipariş açıklamasında bir firma istenirse" in html and "+ Sipariş" not in html
    assert "Firma adı" in html and "her zaman son eşitlik bozucu" in html
    assert "Zorunlu kısıtlar" in html


def test_arrows_change_the_draft_without_saving(screen: Screen) -> None:
    before = screen.path.read_text()
    form = {"ranking": ["total_cost", "hq_proximity"], "op": "up:hq_proximity"}

    html = screen.client.post("/admin/rules/ranking/draft", data=form).text

    assert order_of(html) == ["hq_proximity", "total_cost"]
    assert "Kaydedilmemiş değişiklik var." in html
    assert screen.path.read_text() == before


def test_saving_writes_rules_yaml_and_the_next_quote_uses_it(screen: Screen) -> None:
    assert screen.client.post("/api/v1/quotes", json=ORDER).json()["carrier"] == "S-Logistics"

    html = screen.client.post("/admin/rules/ranking", data={"ranking": ["hq_proximity", "total_cost"]}).text

    assert "Kaydedildi" in html
    assert "ranking:\n  - hq_proximity\n  - total_cost\n  - name\n" in screen.path.read_text()
    data = screen.client.post("/api/v1/quotes", json=ORDER).json()
    assert (data["carrier"], data["total_cost"]) == ("X-Logistics", "705.00")
    assert "Belirleyici kriter: merkezin çıkış noktasına uzaklığı" in data["explanation"]


def test_saving_with_every_criterion_removed_is_refused(screen: Screen) -> None:
    before = screen.path.read_text()

    html = screen.client.post("/admin/rules/ranking", data={}).text

    assert "Kaydedilemedi" in html and "en az bir sıralama kriteri" in html
    assert screen.path.read_text() == before
    assert screen.client.post("/api/v1/quotes", json=ORDER).json()["carrier"] == "S-Logistics"


def test_quote_page_shows_the_current_priority(screen: Screen) -> None:
    html = screen.client.get("/admin/quote").text

    assert "Toplam ücret → Merkezin çıkış noktasına uzaklığı → Firma adı" in html
    assert "Sipariş açıklamasında istenen firma varsa ve uygunsa önce o önerilir." in html


def test_a_broken_file_keeps_the_last_good_rules_and_the_page_says_so(screen: Screen) -> None:
    good = screen.path.read_text()
    assert "Dosya geçersiz" not in screen.client.get("/admin/rules").text  # the valid file has been read once
    later = screen.path.stat().st_mtime_ns + 1_000_000_000

    screen.path.write_text(good.replace("  - total_cost", "  - totl_cost"))
    os.utime(screen.path, ns=(later, later))
    html = screen.client.get("/admin/rules").text
    quote = screen.client.post("/api/v1/quotes", json=ORDER).json()

    assert "Dosya geçersiz" in html and "son geçerli kurallar" in html
    assert order_of(html) == ["total_cost", "hq_proximity"]
    assert quote["carrier"] == "S-Logistics"
    assert any("son geçerli kurallar" in warning for warning in quote["warnings"])
