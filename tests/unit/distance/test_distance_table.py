"""config/distances.yaml: validated, re-read when edited (no restart), a broken edit keeps the last good table."""

import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.clients.distance.chain import DistanceProvider, DistanceSource
from app.clients.distance.static_table import DistanceTableError, FileDistanceTable, parse_table
from tests.fakes import FakeRouting, shipped_distance_config

_, CITIES = shipped_distance_config()
CASE = "- [Miami, Orlando, 235]\n- [Tampa, Orlando, 85]\n"


def write(path: Path, text: str, stamp: int) -> None:
    """Write and set a distinct modification time (two writes within one tick must still count as a change)."""
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(stamp, stamp))


@pytest.fixture
def table_file(tmp_path: Path) -> Path:
    path = tmp_path / "distances.yaml"
    write(path, CASE, 1_000_000_000)
    return path


def test_a_pair_added_to_the_file_applies_on_the_next_lookup(table_file: Path) -> None:
    table = FileDistanceTable(table_file, CITIES.lookup)
    assert table.lookup("Orlando", "Savannah") is None

    write(table_file, CASE + "- [Orlando, Savannah, 280]\n", 2_000_000_000)

    assert table.lookup("Savannah", "Orlando") == 280
    assert table.problem is None


def test_an_added_pair_overrides_a_routing_answer_at_once(table_file: Path) -> None:
    routing = FakeRouting(miles=Decimal("284.6"))
    distances = DistanceProvider(CITIES, FileDistanceTable(table_file, CITIES.lookup), routing=routing)
    assert distances.miles("Orlando", "Savannah").source is DistanceSource.ORS

    write(table_file, CASE + "- [Orlando, Savannah, 280]\n", 2_000_000_000)
    result = distances.miles("Orlando", "Savannah")

    assert (result.miles, result.source) == (280, DistanceSource.CASE_TABLE)


def test_a_broken_edit_keeps_the_last_good_table_and_says_so(table_file: Path) -> None:
    table = FileDistanceTable(table_file, CITIES.lookup)

    write(table_file, "- [Miami, Orlando, -5]\n", 2_000_000_000)

    assert table.lookup("Miami", "Orlando") == 235
    assert table.problem is not None
    assert "son geçerli mesafe tablosu kullanılıyor" in table.problem
    assert "row 1: miles must be a positive number" in table.problem


def test_the_warning_reaches_the_distance_result_and_clears_after_a_fix(table_file: Path) -> None:
    distances = DistanceProvider(CITIES, FileDistanceTable(table_file, CITIES.lookup))

    write(table_file, "[[[", 2_000_000_000)
    broken = distances.miles("Miami", "Orlando")
    write(table_file, CASE, 3_000_000_000)
    fixed = distances.miles("Miami", "Orlando")

    assert broken.miles == fixed.miles == 235
    assert len(broken.warnings) == 1 and "geçersiz" in broken.warnings[0]
    assert fixed.warnings == ()


def test_a_broken_file_at_startup_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "distances.yaml"
    write(path, "- [Miami, Miami, 10]\n", 1_000_000_000)

    with pytest.raises(DistanceTableError, match="one city"):
        FileDistanceTable(path)


def test_city_names_are_written_as_the_catalog_spells_them() -> None:
    table = parse_table("- [ft lauderdale, MIAMI, 30]\n", CITIES.lookup)

    assert table.lookup("Fort Lauderdale", "Miami") == 30


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{Miami: 1}", "expected a list"),
        ("- [Miami, Orlando]\n", "row 1: expected [city, city, miles]"),
        ("- [Miami, 3, 10]\n", "row 1: city names must be text"),
        ("- [Miami, Orlando, many]\n", "row 1: miles must be a positive number"),
        ("- [Miami, Orlando, true]\n", "row 1: miles must be a positive number"),
        ("- [Miami, Orlando, 235]\n- [Orlando, Miami, 240]\n", "row 2: Orlando - Miami is listed twice"),
    ],
)
def test_invalid_rows_are_named(text: str, message: str) -> None:
    with pytest.raises(DistanceTableError, match=message.replace("[", r"\[")):
        parse_table(text)


def test_the_same_pair_twice_with_the_same_miles_is_fine() -> None:
    assert parse_table("- [Miami, Orlando, 235]\n- [Orlando, Miami, 235]\n").lookup("Miami", "Orlando") == 235
