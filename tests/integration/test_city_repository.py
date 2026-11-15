"""PostgresCityRepository against the real `cities` table (each test is rolled back)."""

import pytest

from app.models.city import City
from app.repositories.city_repository import PostgresCityRepository

pytestmark = pytest.mark.db

ORLAND = City("Testorland", "CA", 39.7474, -122.1964)
ORLAND_PARK = City("Testorland Park", "IL", 41.6303, -87.8539)
PETE = City("St. Testersburg", "FL", 27.7676, -82.6403)
WINSTON = City("Testwinston-Salemtest", "NC", 36.0999, -80.2442)


def test_search_matches_name_start_before_word_start_ignoring_case_and_dots(cities: PostgresCityRepository) -> None:
    cities.add([ORLAND_PARK, ORLAND, PETE, WINSTON])

    assert [c.name for c in cities.search("testorland")] == ["Testorland Park", "Testorland"]  # insertion order
    assert [c.name for c in cities.search("st testers")] == ["St. Testersburg"]  # 'St.' == 'st'
    assert [c.name for c in cities.search("testersburg")] == ["St. Testersburg"]  # later word
    assert [c.name for c in cities.search("salemtest")] == ["Testwinston-Salemtest"]  # after a hyphen
    assert cities.search("orland park") == []  # middle of a word does not count


def test_find_is_case_insensitive_and_returns_coordinates(cities: PostgresCityRepository) -> None:
    cities.add([PETE])

    assert cities.find("ST TESTERSBURG") == PETE
    assert cities.find("Nowhere Testville") is None


def test_a_stored_name_keeps_its_first_row(cities: PostgresCityRepository) -> None:
    cities.add([ORLAND])
    cities.add([City("TESTORLAND", "ME", 44.0, -69.0), ORLAND_PARK])

    assert cities.find("testorland") == ORLAND
    assert cities.find("testorland park") == ORLAND_PARK


def test_like_wildcards_in_the_query_are_literal(cities: PostgresCityRepository) -> None:
    cities.add([ORLAND])

    assert cities.search("%") == []
    assert cities.search("_estorland") == []
