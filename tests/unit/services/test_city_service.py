"""CityService with fakes: local first, ORS only when nothing local matches (quota guards), found cities stored."""

from pathlib import Path

from app.clients.distance.cities import load_city_directory
from app.clients.distance.static_table import load_static_table
from app.models.city import City, CitySource
from app.services.city_service import (
    ONLINE_DISABLED,
    ONLINE_FAILED,
    OUTAGE_PAUSE_SECONDS,
    CityService,
)
from tests.fakes import FakePlaces, InMemoryCityRepository, shipped_distance_config

TABLE = load_static_table(Path("config/distances.yaml"))
# The case catalog alone keeps these tests about the ORS rules small; one test uses every shipped city.
DIRECTORY = load_city_directory(Path("config/cities.csv"), Path("config/city_aliases.yaml"), TABLE.city_names())
SHIPPED = shipped_distance_config()[1]

ORLANDO = City("Orlando", "FL", 28.5383, -81.3792)
ORLAND = City("Orland", "CA", 39.7474, -122.1964)
ORLAND_PARK = City("Orland Park", "IL", 41.6303, -87.8539)
BOCA = City("Boca Raton", "FL", 26.3683, -80.1289)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def service(
    places: FakePlaces | None = None, repo: InMemoryCityRepository | None = None, clock: Clock | None = None
) -> CityService:
    repo = repo if repo is not None else InMemoryCityRepository()
    return CityService(DIRECTORY, repo, places, clock=clock or Clock())


def names(result: object) -> list[str]:
    return [s.name for s in result.items]  # type: ignore[attr-defined]


def test_one_or_two_letters_never_reach_ors() -> None:
    places = FakePlaces([City("Qq Town", "TX", 30.0, -97.0)])

    assert names(service(places).suggest("o")) == ["Oklahoma City", "Orlando"]
    assert names(service(places).suggest("qq")) == []
    assert places.calls == []


def test_any_local_match_means_no_ors_request() -> None:
    places = FakePlaces([ORLAND, ORLAND_PARK])

    result = service(places, InMemoryCityRepository([ORLAND])).suggest("orl")

    assert names(result) == ["Orlando", "Orland", "New Orleans"]  # catalog, stored, then a later word
    assert places.calls == []


def test_shipped_us_cities_answer_without_ors() -> None:
    places = FakePlaces([City("Amsterdam", "NY", 42.9, -74.2)])
    cities = CityService(SHIPPED, InMemoryCityRepository(), places, clock=Clock())

    assert names(cities.suggest("a")) == ["Austin", "Albuquerque", "Atlanta", "Arlington", "Aurora"]
    assert names(cities.suggest("ams")) == ["Amsterdam"]
    assert names(cities.suggest("miami")) == ["Miami", "Miami Gardens", "Miami Beach", "Miami Lakes", "Miamisburg"]
    assert places.calls == []


def test_no_local_match_asks_ors_and_stores_what_it_finds() -> None:
    boca_west = City("Boca West", "FL", 26.38, -80.16)
    places, repo = FakePlaces([BOCA, boca_west]), InMemoryCityRepository()

    result = service(places, repo).suggest("Boca")

    assert [(s.name, s.state, s.source) for s in result.items] == [
        ("Boca Raton", "FL", CitySource.ORS),
        ("Boca West", "FL", CitySource.ORS),
    ]
    assert result.warnings == ()
    assert places.calls == ["Boca"]
    assert sorted(repo.rows) == ["boca raton", "boca west"]


def test_a_city_found_once_comes_from_the_database_afterwards() -> None:
    places, repo = FakePlaces([BOCA]), InMemoryCityRepository()
    service(places, repo).suggest("boca")

    later = service(FakePlaces(), repo).suggest("BOCA r")  # a fresh process: nothing remembered in memory

    assert names(later) == ["Boca Raton"]
    assert later.items[0].source is CitySource.ORS


def test_the_same_query_is_sent_to_ors_once() -> None:
    places = FakePlaces([BOCA])
    cities = service(places)

    cities.suggest("boca")
    cities.suggest("BOCA")
    cities.suggest(" boca ")

    assert places.calls == ["boca"]


def test_longer_queries_skip_ors_once_a_shorter_answer_was_complete() -> None:
    places = FakePlaces([BOCA])  # fewer than a full page: ORS had nothing more
    cities = service(places)

    cities.suggest("boc")
    cities.suggest("bocx")
    cities.suggest("boca grande")

    assert places.calls == ["boc"]


def test_a_full_page_from_ors_does_not_stop_longer_queries() -> None:
    page = [City(f"Bocville {i}", "TX", 30.0, -97.0) for i in range(10)]
    places = FakePlaces([*page, BOCA])
    cities = service(places)

    cities.suggest("boc")
    cities.suggest("bocz")

    assert places.calls == ["boc", "bocz"]


def test_ors_outage_shows_a_note_and_pauses() -> None:
    clock, places = Clock(), FakePlaces([BOCA], fail=True)
    cities = service(places, clock=clock)

    first = cities.suggest("boca")
    paused = cities.suggest("marfa")
    clock.now += OUTAGE_PAUSE_SECONDS + 1
    places.fail = False
    recovered = cities.suggest("boca")

    assert (names(first), first.warnings) == ([], (ONLINE_FAILED,))
    assert (names(paused), paused.warnings) == ([], (ONLINE_FAILED,))
    assert names(recovered) == ["Boca Raton"]
    assert places.calls == ["boca", "boca"]  # a failed query is asked again; the pause skipped 'marfa'


def test_without_an_ors_key_only_local_cities_are_shown() -> None:
    cities = service(places=None)

    assert cities.suggest("boca").warnings == (ONLINE_DISABLED,)
    assert cities.suggest("o").warnings == ()  # too short to have asked anyway


def test_a_broken_city_table_still_suggests_catalog_cities() -> None:
    places = FakePlaces([ORLAND])

    result = service(places, InMemoryCityRepository(fail=True)).suggest("orl")

    assert names(result) == ["Orlando", "New Orleans"]


def test_repeated_names_from_ors_are_stored_once_first_one_wins() -> None:
    springfields = [City("Springfield", "IL", 39.8, -89.6), City("Springfield", "MO", 37.2, -93.3)]
    repo = InMemoryCityRepository()

    result = service(FakePlaces(springfields), repo).suggest("springf")

    assert [(s.name, s.state) for s in result.items] == [("Springfield", "IL")]
    assert repo.rows["springfield"].state == "IL"


def test_state_after_a_comma_is_not_sent_to_ors() -> None:
    places = FakePlaces([BOCA])

    result = service(places).suggest("boca, fl")

    assert places.calls == ["boca"]
    assert names(result) == ["Boca Raton"]


def test_limit_is_respected() -> None:
    assert len(service().suggest("s", limit=3).items) == 3
