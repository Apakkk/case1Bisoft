"""config/us_cities.csv and the script that builds it: cities and towns only, never neighbourhoods."""

import csv
from pathlib import Path

import pytest

from scripts.build_us_cities import select
from tests.fakes import shipped_distance_config

_, CITIES = shipped_distance_config()


def read_csv(path: str) -> list[dict[str, str]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return list(csv.DictReader(line for line in lines if not line.startswith("#")))


ROWS = read_csv("config/us_cities.csv")


def test_the_shipped_list_is_one_row_per_name() -> None:
    names = [row["name"] for row in ROWS]

    assert 4_500 < len(names) < 6_000
    assert len({name.casefold() for name in names}) == len(names)
    assert not [name for name in names if "," in name or "/" in name or "(" in name]


def test_every_catalog_city_keeps_its_catalog_data() -> None:
    catalog = read_csv("config/cities.csv")

    for row in catalog:
        assert CITIES.lookup(row["name"]) == row["name"]
        assert CITIES.state_of(row["name"]) == row["state"]
        assert CITIES.coordinates_of(row["name"]) == (float(row["lat"]), float(row["lon"]))
    assert CITIES.population["New York"] > 8_000_000  # through the 'New York City' alias


@pytest.mark.parametrize(
    "neighbourhood", ["Adams Morgan", "Foggy Bottom", "Downtown DC", "Back Bay", "Dorchester", "Little Havana"]
)
def test_neighbourhoods_are_not_cities(neighbourhood: str) -> None:
    assert CITIES.lookup(neighbourhood) is None


def test_a_borough_name_is_the_city_of_that_name_elsewhere() -> None:
    assert CITIES.state_of("Manhattan") == "KS"  # not New York's borough
    assert CITIES.state_of("Brooklyn") == "OH"


def geonames(name: str, state: str, population: int, code: str = "PPL", country: str = "US") -> list[str]:
    line = [""] * 19
    line[1], line[4], line[5], line[7], line[8], line[10], line[14] = (
        name,
        "30.0",
        "-90.0",
        code,
        country,
        state,
        str(population),
    )
    return line


def census(state: str, name: str) -> list[str]:
    return [state, "", "", name]


def test_select_keeps_census_places_and_names_them_plainly() -> None:
    places = [
        census("FL", "Miami city"),
        census("WA", "Sammamish city"),
        census("NY", "New York city"),
        census("ID", "Boise City city"),
        census("MA", "Weymouth Town city"),
        census("TN", "Nashville-Davidson metropolitan government (balance)"),
        census("MO", "Springfield city"),
        census("IL", "Springfield city"),
        census("CA", "Bayview CDP"),
        census("FL", "Princeton CDP"),
    ]
    lines = [
        geonames("Miami", "FL", 442_241),
        geonames("Little Havana", "FL", 53_430, code="PPLX"),  # a section of a city
        geonames("Allapattah", "FL", 54_289),  # labelled a town, but not a Census place
        geonames("City of Sammamish", "WA", 45_780),
        geonames("New York City", "NY", 8_804_190),
        geonames("Boise", "ID", 235_684),
        geonames("Weymouth", "MA", 54_395),
        geonames("Nashville", "TN", 689_447),
        geonames("Springfield", "IL", 114_394),
        geonames("Springfield", "MO", 170_188),
        geonames("Bayview-Hunters Point", "CA", 33_000),  # a San Francisco neighbourhood, not the Bayview CDP
        geonames("Princeton (historical)", "FL", 6_000),
        geonames("Paris", "FR", 2_138_551, country="FR"),
    ]

    rows = select(lines, places)

    assert [(name, state) for name, state, *_ in rows] == [
        ("Boise", "ID"),
        ("Miami", "FL"),
        ("Nashville", "TN"),
        ("New York City", "NY"),
        ("Sammamish", "WA"),
        ("Springfield", "MO"),  # one row per name: the most populous
        ("Weymouth", "MA"),
    ]
