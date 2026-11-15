from pathlib import Path

import pytest

from app.clients.distance.cities import load_city_directory
from app.clients.distance.haversine import haversine_miles
from app.clients.distance.static_table import load_static_table
from tests.case_data import CASE_DISTANCES

TABLE = load_static_table(Path("config/distances.yaml"))
CITIES = load_city_directory(Path("config/cities.csv"), Path("config/city_aliases.yaml"), TABLE.city_names())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ft. Lauderdale", "Fort Lauderdale"),
        ("ft lauderdale", "Fort Lauderdale"),
        ("  miami  ", "Miami"),
        ("Miami, FL", "Miami"),
        ("FORT   LAUDERDALE", "Fort Lauderdale"),
        ("jax", "Jacksonville"),
        ("saint louis", "St. Louis"),
        ("st louis", "St. Louis"),
        ("springfield", "Springfield"),  # unknown: tidied, left for geocoding
    ],
)
def test_city_names_are_normalized(raw: str, expected: str) -> None:
    assert CITIES.normalize(raw) == expected


def test_shipped_table_is_exactly_the_case_table() -> None:
    for pair, miles in CASE_DISTANCES.items():
        a, b = sorted(pair)
        assert TABLE.lookup(a, b) == miles
        assert TABLE.lookup(b, a) == miles  # symmetric
    assert len(TABLE.city_names()) == 8


def test_every_case_city_has_coordinates() -> None:
    for city in TABLE.city_names():
        assert CITIES.coordinates_of(city) is not None, city


def test_haversine_miami_atlanta_is_about_606_miles() -> None:
    miami, atlanta = CITIES.coordinates_of("Miami"), CITIES.coordinates_of("Atlanta")
    assert miami is not None and atlanta is not None

    assert haversine_miles(miami, atlanta) == pytest.approx(606, abs=3)
