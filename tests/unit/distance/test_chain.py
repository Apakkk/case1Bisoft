"""Distance chain and city resolution, with fakes for the cache, the city table and the routing service."""

from decimal import Decimal

import pytest

from app.clients.distance.chain import DistanceProvider, DistanceSource, LocationProblem, UnknownLocationError
from app.models.city import City, Place
from tests.case_data import CASE_DISTANCES
from tests.fakes import FakeRouting, InMemoryCityRepository, InMemoryDistanceCache, shipped_distance_config

TABLE, CITIES = shipped_distance_config()

MARFA = City("Marfa", "TX", 30.3094, -104.0206)  # ~1,800 people: not in us_cities.csv
BOCA_WEST = City("Boca West", "FL", 26.3806, -80.1598)


def provider(
    cache: InMemoryDistanceCache | None = None,
    routing: FakeRouting | None = None,
    stored: InMemoryCityRepository | None = None,
) -> DistanceProvider:
    return DistanceProvider(CITIES, TABLE, cache, routing, stored)


def problem_of(city: str, distances: DistanceProvider | None = None) -> UnknownLocationError:
    with pytest.raises(UnknownLocationError) as error:
        (distances or provider()).normalize(city)
    return error.value


# --- the case table always wins --------------------------------------------------------------------


TABLE_PAIRS = [(a, b, miles) for pair, miles in CASE_DISTANCES.items() for a, b in (sorted(pair), sorted(pair)[::-1])]


@pytest.mark.parametrize(("a", "b", "miles"), TABLE_PAIRS)
def test_every_case_table_pair_in_both_directions_never_reaches_the_routing_service(
    a: str, b: str, miles: Decimal
) -> None:
    routing = FakeRouting(fail=True)  # any request would fail the lookup

    result = provider(InMemoryDistanceCache(), routing).miles(a, b)

    assert (result.miles, result.source, result.approximate) == (miles, DistanceSource.CASE_TABLE, False)
    assert routing.route_calls == routing.geocode_calls == []


@pytest.mark.parametrize(
    ("a", "b", "miles"),
    [
        ("Ft. Lauderdale", "MIAMI, FL", 30),
        ("miami, florida", "  orlando ", 235),
        ("jax", "Tampa", 200),
        ("Savannah, GA", "JACKSONVILLE", 140),
    ],
)
def test_other_spellings_of_table_cities_still_use_the_table(a: str, b: str, miles: int) -> None:
    routing = FakeRouting(fail=True)

    result = provider(routing=routing).miles(a, b)

    assert (result.miles, result.source) == (miles, DistanceSource.CASE_TABLE)
    assert routing.route_calls == routing.geocode_calls == []


def test_the_table_wins_over_a_routing_answer_stored_earlier() -> None:
    cache = InMemoryDistanceCache()
    cache.put("Miami", "Orlando", Decimal("233.4"), "ors")

    assert provider(cache).miles("Miami", "Orlando").miles == 235


def test_same_city_is_zero() -> None:
    result = provider().miles("Tampa", "tampa")

    assert (result.miles, result.source) == (0, DistanceSource.SAME_CITY)


def test_routing_result_is_cached_and_reused() -> None:
    cache, routing = InMemoryDistanceCache(), FakeRouting(miles=Decimal("281.4"))
    distances = provider(cache, routing)

    first = distances.miles("Tampa", "Miami")
    second = distances.miles("Miami", "Tampa")

    assert (first.miles, first.source) == (Decimal("281.4"), DistanceSource.ORS)
    assert (second.miles, second.source) == (Decimal("281.4"), DistanceSource.CACHE)
    assert len(routing.route_calls) == 1


def test_without_routing_service_haversine_is_used_and_flagged() -> None:
    result = provider().miles("Tampa", "Miami", approximate_factor=Decimal("1.2"))

    assert result.source is DistanceSource.HAVERSINE
    assert result.approximate
    assert result.miles == pytest.approx(Decimal("247"), abs=3)  # ~205 mi straight line x 1.2


def test_routing_outage_falls_back_to_haversine_with_a_warning() -> None:
    result = provider(routing=FakeRouting(fail=True)).miles("Tampa", "Miami")

    assert result.source is DistanceSource.HAVERSINE
    assert result.warnings == ("Harita servisi kullanılamadı; mesafe yaklaşık hesaplandı.",)


def test_broken_cache_does_not_fail_the_lookup() -> None:
    class BrokenCache(InMemoryDistanceCache):
        def get(self, a: str, b: str) -> Decimal | None:
            raise RuntimeError("database down")

    result = provider(BrokenCache(), FakeRouting(miles=Decimal("281.4"))).miles("Tampa", "Miami")

    assert result.source is DistanceSource.ORS


# --- which city: shipped, stored, confirmed online, or refused ------------------------------------------


def test_shipped_us_cities_need_no_geocoding_request() -> None:
    routing = FakeRouting(miles=Decimal("1650.0"))
    distances = provider(routing=routing)

    assert distances.normalize("amarillo") == "Amarillo"
    assert distances.state_of("Amarillo") == "TX"
    distances.miles("Miami", "Amarillo")
    assert routing.geocode_calls == []
    assert routing.route_calls == [((25.7617, -80.1918), (35.222, -101.8313))]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Miami, FL", "Miami"), ("miami, florida", "Miami"), ("Washington, D.C.", "Washington"), ("Paris", "Paris")],
)
def test_a_state_after_the_comma_is_accepted_when_it_is_the_citys(raw: str, expected: str) -> None:
    assert provider().normalize(raw) == expected


def test_a_bare_name_resolves_to_the_known_city_and_says_which_state() -> None:
    distances = provider()

    assert distances.normalize("Paris") == "Paris"
    assert distances.state_of("Paris") == "TX"  # shown as 'Paris, TX': nothing is silent


def test_another_state_is_refused_not_ignored() -> None:
    error = problem_of("Portland, ME")

    assert error.problem is LocationProblem.OTHER_STATE
    assert error.suggestions == (Place("Portland", "OR"),)
    assert error.message == "'Portland, ME' tanınmıyor: şehirler adıyla tanınır ve bu ad Portland, OR olarak kayıtlı."


def test_a_country_is_refused_with_the_us_city_of_that_name() -> None:
    routing = FakeRouting()

    error = problem_of("Amsterdam, Netherlands", provider(routing=routing))

    assert error.problem is LocationProblem.OUTSIDE_US
    assert error.suggestions == (Place("Amsterdam", "NY"),)
    assert error.message == (
        "Yalnızca ABD şehirleri destekleniyor; 'Netherlands' bir ABD eyaleti değil. ABD'de bu adla: Amsterdam, NY."
    )
    assert (
        error.detail == "only US cities are supported; 'Netherlands' is not a US state (US city with this name: "
        "Amsterdam, NY)"
    )
    assert routing.geocode_calls == []  # refused before any request


@pytest.mark.parametrize(("typo", "meant"), [("Tamap", "Tampa, FL"), ("Jacksonvile", "Jacksonville, FL")])
def test_a_typo_is_not_guessed_but_answered_with_did_you_mean(typo: str, meant: str) -> None:
    look_alike = City("Tamaqua", "PA", 40.79, -75.96)  # what a fuzzy geocoder may return instead
    routing = FakeRouting(places={typo: [look_alike]})

    error = problem_of(typo, provider(routing=routing))

    assert error.problem is LocationProblem.NOT_FOUND
    assert meant in [place.label for place in error.suggestions]
    assert error.message.startswith(f"'{typo}' adında bir ABD şehri bulunamadı. Bunu mu demek istediniz: ")
    assert routing.geocode_calls == [typo]


def test_a_small_town_is_confirmed_by_exact_name_once_and_stored() -> None:
    routing = FakeRouting(places={"Marfa": [City("Marfa Lights", "TX", 30.3, -103.9), MARFA]})
    stored = InMemoryCityRepository()
    distances = provider(routing=routing, stored=stored)

    assert distances.normalize("marfa") == "Marfa"  # the second hit, the one with the typed name
    assert distances.normalize("MARFA") == "Marfa"
    assert distances.state_of("Marfa") == "TX"
    assert routing.geocode_calls == ["Marfa"]
    assert stored.find("marfa") == MARFA

    later = provider(routing=FakeRouting(fail=True), stored=stored)  # next run: from the cities table
    assert later.normalize("Marfa") == "Marfa"


def test_an_unknown_name_is_asked_once_per_run() -> None:
    routing = FakeRouting()
    distances = provider(routing=routing)

    for _ in range(3):
        problem_of("Atlantis", distances)

    assert routing.geocode_calls == ["Atlantis"]


def test_a_state_narrows_the_online_check() -> None:
    routing = FakeRouting(places={"Marfa, TX": [MARFA], "Marfa, OK": [MARFA]})
    distances = provider(routing=routing)

    assert distances.normalize("Marfa, TX") == "Marfa"
    assert problem_of("Marfa, OK", distances).problem is LocationProblem.NOT_FOUND


def test_a_routing_outage_leaves_an_unknown_city_unconfirmed_and_retries_later() -> None:
    routing = FakeRouting(fail=True)
    distances = provider(routing=routing)

    error = problem_of("Marfa", distances)
    problem_of("Marfa", distances)

    assert error.problem is LocationProblem.UNVERIFIED
    assert routing.geocode_calls == ["Marfa", "Marfa"]  # an outage is not remembered as "no such city"


def test_without_routing_service_an_unknown_city_is_unconfirmed() -> None:
    error = problem_of("Atlantis")

    assert error.problem is LocationProblem.UNVERIFIED
    assert error.city == "Atlantis"


def test_a_stored_city_keeps_its_spelling_and_needs_no_request() -> None:
    routing = FakeRouting(miles=Decimal("45.0"))
    distances = provider(routing=routing, stored=InMemoryCityRepository([BOCA_WEST]))

    assert distances.normalize("BOCA WEST") == "Boca West"
    assert distances.miles("Miami", "boca west").source is DistanceSource.ORS
    assert routing.geocode_calls == []
    assert routing.route_calls == [((25.7617, -80.1918), (26.3806, -80.1598))]


def test_a_broken_city_table_still_confirms_the_city_online() -> None:
    routing = FakeRouting(places={"Marfa": [MARFA]})
    distances = provider(routing=routing, stored=InMemoryCityRepository(fail=True))

    assert distances.normalize("marfa") == "Marfa"
    assert distances.miles("Miami", "Marfa").source is DistanceSource.ORS
