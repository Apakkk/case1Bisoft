"""CityService with fakes: local first, ORS only when needed (quota guards), found cities are stored."""

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
from tests.fakes import FakePlaces, InMemoryCityRepository

TABLE = load_static_table(Path("config/distances.yaml"))
DIRECTORY = load_city_directory(Path("config/cities.csv"), Path("config/city_aliases.yaml"), TABLE.city_names())

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
    places = FakePlaces([ORLAND])

    assert names(service(places).suggest("o")) == ["Oklahoma City", "Orlando", "New Orleans"]
    assert names(service(places).suggest("or")) == ["Orlando", "New Orleans"]
    assert places.calls == []


def test_five_local_matches_mean_no_ors_request() -> None:
    stored = [ORLAND, ORLAND_PARK, City("Orlinda", "TN", 36.6, -86.7), City("Orleans", "MA", 41.8, -69.9)]
    places = FakePlaces([BOCA])

    result = service(places, InMemoryCityRepository(stored)).suggest("orl")

    assert names(result) == ["Orlando", "Orland", "Orland Park", "Orlinda", "Orleans"]  # stored = ORS order
    assert places.calls == []


def test_too_few_local_matches_ask_ors_and_store_what_it_finds() -> None:
    places, repo = FakePlaces([ORLANDO, ORLAND, ORLAND_PARK]), InMemoryCityRepository()

    result = service(places, repo).suggest("Orl")

    assert [(s.name, s.state, s.source) for s in result.items] == [
        ("Orlando", "FL", CitySource.CATALOG),
        ("Orland", "CA", CitySource.ORS),
        ("Orland Park", "IL", CitySource.ORS),
        ("New Orleans", "LA", CitySource.CATALOG),
    ]
    assert result.warnings == ()
    assert places.calls == ["Orl"]
    assert sorted(repo.rows) == ["orland", "orland park"]  # the catalog city is not stored again


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
    places = FakePlaces([ORLAND, ORLAND_PARK])  # fewer than a full page: ORS had nothing more
    cities = service(places)

    cities.suggest("orl")
    cities.suggest("orla")
    cities.suggest("orland p")

    assert places.calls == ["orl"]


def test_a_full_page_from_ors_does_not_stop_longer_queries() -> None:
    page = [City(f"Orlville {i}", "TX", 30.0, -97.0) for i in range(10)]
    places = FakePlaces([*page, ORLAND])
    cities = service(places)

    cities.suggest("orl")
    cities.suggest("orla")

    assert places.calls == ["orl", "orla"]


def test_ors_outage_shows_local_results_with_a_note_and_pauses() -> None:
    clock, places = Clock(), FakePlaces([BOCA], fail=True)
    cities = service(places, clock=clock)

    first = cities.suggest("orl")
    paused = cities.suggest("boca")
    clock.now += OUTAGE_PAUSE_SECONDS + 1
    places.fail = False
    recovered = cities.suggest("boca")

    assert (names(first), first.warnings) == (["Orlando", "New Orleans"], (ONLINE_FAILED,))
    assert (names(paused), paused.warnings) == ([], (ONLINE_FAILED,))
    assert names(recovered) == ["Boca Raton"]
    assert places.calls == ["orl", "boca"]


def test_without_an_ors_key_only_local_cities_are_shown() -> None:
    cities = service(places=None)

    assert cities.suggest("boca").warnings == (ONLINE_DISABLED,)
    assert cities.suggest("o").warnings == ()  # too short to have asked anyway


def test_a_broken_city_table_still_suggests_catalog_cities() -> None:
    places = FakePlaces([ORLAND])

    result = service(places, InMemoryCityRepository(fail=True)).suggest("orl")

    assert names(result) == ["Orlando", "Orland", "New Orleans"]


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
