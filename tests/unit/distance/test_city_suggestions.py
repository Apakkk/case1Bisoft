"""Ranking of city suggestions (pure): what was typed starts the name, most populous first, top 5.

Real-data tests use the shipped files (catalog + us_cities.csv); rule tests use a few hand-made entries.
"""

import pytest

from app.clients.distance.cities import CityEntry, city_key, rank_suggestions, word_tails
from app.models.city import City, CitySource
from tests.fakes import shipped_distance_config

_, CITIES = shipped_distance_config()
SHIPPED = CITIES.entries()


def names(query: str, entries: tuple[CityEntry, ...] | list[CityEntry] = SHIPPED, limit: int = 5) -> list[str]:
    return [s.name for s in rank_suggestions(query, entries, limit)]


def shipped(name: str, state: str, population: int) -> CityEntry:
    return CityEntry(city_key(name), name, state, CitySource.CATALOG, population=population, tails=word_tails(name))


def found(*cities: tuple[str, str]) -> list[CityEntry]:
    """Cities found online, in the order ORS ranked them."""
    return [
        CityEntry.of(City(name, state, 0.0, 0.0), CitySource.ORS, rank) for rank, (name, state) in enumerate(cities)
    ]


# --- with the shipped cities -------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["a", "A", " a "])
def test_one_letter_lists_only_names_starting_with_it_most_populous_first(query: str) -> None:
    # Los Angeles and San Antonio have a word starting with 'a': one letter is too little for that.
    assert names(query) == ["Austin", "Albuquerque", "Atlanta", "Arlington", "Aurora"]


def test_the_orlando_example() -> None:
    assert names("o") == ["Oklahoma City", "Omaha", "Oakland", "Orlando", "Oxnard"]
    assert names("orl")[0] == "Orlando"


def test_more_letters_narrow_down_to_the_small_city() -> None:
    assert names("am") == ["Amarillo", "Ames", "Amherst", "American Fork", "American Canyon"]
    assert names("ams") == ["Amsterdam"]  # Amsterdam, NY (18,000 people)


@pytest.mark.parametrize("query", ["orlando", "ORLANDO", "oRlAnDo", "  Orlando  "])
def test_case_and_spaces_do_not_matter(query: str) -> None:
    assert names(query) == ["Orlando"]


def test_turkish_capital_dotted_i_is_an_i() -> None:
    assert city_key("MİAMİ") == "miami"
    assert names("MİAMİ") == ["Miami", "Miami Gardens", "Miami Beach", "Miami Lakes", "Miamisburg"]


def test_a_later_word_fills_the_rows_left_after_names_that_start_with_it() -> None:
    assert names("lauderdale") == ["Lauderdale Lakes", "Lauderdale-by-the-Sea", "Fort Lauderdale", "North Lauderdale"]
    # The price of "starts with first": five Lau... names leave no row for Fort Lauderdale; "ft" finds it.
    assert "Fort Lauderdale" not in names("lau")
    assert names("ft") == ["Fort Lauderdale"]


def test_aliases_suggest_the_city_they_stand_for_once() -> None:
    assert names("nyc") == ["New York"]
    assert names("jax") == ["Jacksonville"]
    assert names("la")[0] == "Los Angeles"  # the 'LA' alias
    assert names("new") == ["New York", "New Orleans", "Newark", "Newport News", "New Haven"]  # NYC alias not repeated
    assert "St. Louis" in names("saint")


def test_dots_and_accents_are_optional() -> None:
    assert names("st l") == names("st. l") == ["St. Louis"]
    assert names("canon")[0] == "Cañon City"


def test_state_after_a_comma_filters() -> None:
    assert names("orlando, f") == ["Orlando"]
    assert names("orlando, tx") == []
    assert names("portland, OR") == ["Portland"]


@pytest.mark.parametrize("query", ["", "   ", ",", ", FL"])
def test_nothing_typed_suggests_nothing(query: str) -> None:
    assert names(query) == []


def test_unknown_letters_suggest_nothing() -> None:
    assert names("xyz") == []


def test_every_suggestion_carries_its_state() -> None:
    assert [(s.name, s.state) for s in rank_suggestions("ams", SHIPPED)] == [("Amsterdam", "NY")]


# --- the rules, with hand-made entries ------------------------------------------------------------------

ORLANDO = shipped("Orlando", "FL", 334_854)
FORT_LAUDERDALE = shipped("Fort Lauderdale", "FL", 182_760)
LAUDERHILL = shipped("Lauderhill", "FL", 71_579)
OCALA = shipped("Ocala", "FL", 63_591)


def test_population_orders_names_that_start_with_the_query() -> None:
    assert names("o", [OCALA, ORLANDO]) == ["Orlando", "Ocala"]


def test_a_later_word_needs_three_letters() -> None:
    entries = [FORT_LAUDERDALE, LAUDERHILL]

    assert names("la", entries) == ["Lauderhill"]
    assert names("lau", entries) == ["Lauderhill", "Fort Lauderdale"]  # name start first, despite population


def test_lower_case_joining_words_are_not_word_starts() -> None:
    entries = [*found(("Hamptons at Boca Raton", "FL")), shipped("Lauderdale-by-the-Sea", "FL", 6_198)]

    assert names("the", entries) == []
    assert names("sea", entries) == ["Lauderdale-by-the-Sea"]
    assert names("boca", entries) == ["Hamptons at Boca Raton"]


@pytest.mark.parametrize(
    ("query", "entries", "parts"),
    [
        ("orl", [ORLANDO], ("", "Orl", "ando")),
        ("lau", [FORT_LAUDERDALE], ("Fort ", "Lau", "derdale")),
        ("st l", list(SHIPPED), ("", "St. L", "ouis")),
        ("ft", list(SHIPPED), ("Fort Lauderdale", "", "")),  # matched through an alias: nothing to bold
    ],
)
def test_matched_letters_are_marked_for_bold(query: str, entries: list[CityEntry], parts: tuple[str, str, str]) -> None:
    assert rank_suggestions(query, entries)[0].parts == parts


def test_shipped_cities_come_first_and_found_cities_keep_the_ors_order() -> None:
    entries = [OCALA, *found(("Orlinda", "TN"), ("Orla", "TX")), ORLANDO]

    result = rank_suggestions("o", entries)

    assert [(s.name, s.source) for s in result] == [
        ("Orlando", CitySource.CATALOG),
        ("Ocala", CitySource.CATALOG),
        ("Orlinda", CitySource.ORS),
        ("Orla", CitySource.ORS),
    ]


def test_a_found_city_with_a_shipped_name_appears_once_as_shipped() -> None:
    result = rank_suggestions("orlando", [*found(("Orlando", "FL")), *SHIPPED])

    assert [(s.name, s.source) for s in result] == [("Orlando", CitySource.CATALOG)]


def test_most_relevant_found_city_stays_first() -> None:
    # Live ORS answer for 'boca' (2026-11-11): the real city first, nearby communities after it.
    entries = found(
        ("Boca Raton", "FL"), ("Boca Del Mar", "FL"), ("Hamptons at Boca Raton", "FL"), ("Boca Pointe", "FL")
    )

    assert names("boca", entries) == ["Boca Raton", "Boca Del Mar", "Boca Pointe", "Hamptons at Boca Raton"]


def test_one_letter_never_brings_a_stored_community_by_a_later_word() -> None:
    # The screenshot that started this: 'a' listed 'Hamptons at Boca Raton'.
    assert "Hamptons at Boca Raton" not in names("a", [*SHIPPED, *found(("Hamptons at Boca Raton", "FL"))])
