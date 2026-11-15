"""Ranking of city suggestions (pure): case-insensitive, name start before word start, catalog first, top 5."""

from pathlib import Path

import pytest

from app.clients.distance.cities import CityEntry, city_key, load_city_directory, rank_suggestions
from app.clients.distance.static_table import load_static_table
from app.models.city import City, CitySource

TABLE = load_static_table(Path("config/distances.yaml"))
CITIES = load_city_directory(Path("config/cities.csv"), Path("config/city_aliases.yaml"), TABLE.city_names())
CATALOG = CITIES.entries()


def names(query: str, entries: list[CityEntry] = CATALOG, limit: int = 5) -> list[str]:
    return [s.name for s in rank_suggestions(query, entries, limit)]


def found(*cities: tuple[str, str]) -> list[CityEntry]:
    """Cities found online, in the order ORS ranked them."""
    return [
        CityEntry.of(City(name, state, 0.0, 0.0), CitySource.ORS, rank) for rank, (name, state) in enumerate(cities)
    ]


@pytest.mark.parametrize("query", ["o", "O", " o "])
def test_one_letter_suggests_names_starting_with_it_then_words_starting_with_it(query: str) -> None:
    # 'New Orleans' has a word starting with o; 'Boston' only contains it and is not suggested.
    assert names(query) == ["Oklahoma City", "Orlando", "New Orleans"]


@pytest.mark.parametrize("query", ["orlando", "ORLANDO", "oRlAnDo", "  Orlando  "])
def test_case_and_spaces_do_not_matter(query: str) -> None:
    assert names(query) == ["Orlando"]


def test_turkish_capital_dotted_i_is_an_i() -> None:
    assert city_key("MİAMİ") == "miami"
    assert names("MİAMİ") == ["Miami"]


def test_at_most_five_suggestions_in_alphabetical_order() -> None:
    assert names("s") == ["Salt Lake City", "San Antonio", "San Diego", "San Francisco", "Sarasota"]
    assert names("s", limit=2) == ["Salt Lake City", "San Antonio"]


def test_name_start_ranks_before_word_start() -> None:
    assert names("la") == ["Laredo", "Las Vegas", "Los Angeles", "Fort Lauderdale", "Salt Lake City"]


def test_aliases_suggest_the_city_they_stand_for_once() -> None:
    assert names("ft") == ["Fort Lauderdale"]
    assert names("nyc") == ["New York"]
    assert names("saint") == ["St. Louis"]
    assert names("new") == ["New Orleans", "New York"]  # the 'New York City' alias does not repeat New York


def test_dots_in_names_are_optional() -> None:
    assert names("st l") == ["St. Louis"]
    assert names("st. l") == ["St. Louis"]


@pytest.mark.parametrize(
    ("query", "parts"),
    [
        ("orl", ("", "Orl", "ando")),
        ("lau", ("Fort ", "Lau", "derdale")),
        ("st l", ("", "St. L", "ouis")),
        ("ft", ("Fort Lauderdale", "", "")),  # matched through an alias: nothing to bold
    ],
)
def test_matched_letters_are_marked_for_bold(query: str, parts: tuple[str, str, str]) -> None:
    assert rank_suggestions(query, CATALOG)[0].parts == parts


def test_state_after_a_comma_filters() -> None:
    assert names("orlando, f") == ["Orlando"]
    assert names("orlando, tx") == []
    assert names("portland, OR") == ["Portland"]


@pytest.mark.parametrize("query", ["", "   ", ",", ", FL"])
def test_nothing_typed_suggests_nothing(query: str) -> None:
    assert names(query) == []


def test_unknown_letters_suggest_nothing() -> None:
    assert names("xyz") == []


def test_catalog_city_comes_first_and_found_cities_keep_the_ors_order() -> None:
    entries = [*CATALOG, *found(("Orland Park", "IL"), ("Orland", "CA"))]

    result = rank_suggestions("orl", entries)

    assert [(s.name, s.state, s.source) for s in result] == [
        ("Orlando", "FL", CitySource.CATALOG),
        ("Orland Park", "IL", CitySource.ORS),
        ("Orland", "CA", CitySource.ORS),
        ("New Orleans", "LA", CitySource.CATALOG),  # word start ranks after every name start
    ]


def test_a_found_city_with_a_catalog_name_appears_once_as_catalog() -> None:
    result = rank_suggestions("orlando", [*found(("Orlando", "FL")), *CATALOG])

    assert [(s.name, s.source) for s in result] == [("Orlando", CitySource.CATALOG)]


def test_catalog_entries_carry_states() -> None:
    assert {s.state for s in rank_suggestions("miami", CATALOG)} == {"FL"}


def test_most_relevant_found_city_stays_first() -> None:
    # Live ORS answer for 'boca' (2026-11-11): the real city first, nearby communities after it.
    entries = found(
        ("Boca Raton", "FL"), ("Boca Del Mar", "FL"), ("Hamptons at Boca Raton", "FL"), ("Boca Pointe", "FL")
    )

    assert names("boca", entries) == ["Boca Raton", "Boca Del Mar", "Boca Pointe", "Hamptons at Boca Raton"]
