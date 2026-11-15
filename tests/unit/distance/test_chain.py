"""Tier order of the distance chain, using fakes for the cache and the routing service."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.clients.distance.chain import DistanceProvider, DistanceSource, UnknownLocationError
from app.clients.distance.cities import load_city_directory
from app.clients.distance.static_table import load_static_table
from app.models.city import City
from tests.fakes import FakeRouting, InMemoryCityRepository, InMemoryDistanceCache

TABLE = load_static_table(Path("config/distances.yaml"))
CITIES = load_city_directory(Path("config/cities.csv"), Path("config/city_aliases.yaml"), TABLE.city_names())


def provider(cache: InMemoryDistanceCache | None = None, routing: FakeRouting | None = None) -> DistanceProvider:
    return DistanceProvider(CITIES, TABLE, cache, routing)


def test_same_city_is_zero() -> None:
    result = provider().miles("Tampa", "tampa")

    assert (result.miles, result.source) == (0, DistanceSource.SAME_CITY)


def test_case_table_wins_and_never_calls_the_routing_service() -> None:
    routing = FakeRouting()

    result = provider(routing=routing).miles("Ft. Lauderdale", "Miami")

    assert (result.miles, result.source, result.approximate) == (30, DistanceSource.CASE_TABLE, False)
    assert routing.route_calls == []


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


def test_unknown_city_is_geocoded_once() -> None:
    routing = FakeRouting(geocodes={"Ocala": (29.1872, -82.1401)}, miles=Decimal("80.0"))
    distances = provider(InMemoryDistanceCache(), routing)

    distances.miles("Ocala", "Orlando")
    distances.miles("Ocala", "Tampa")

    assert routing.geocode_calls == ["Ocala"]


def test_unknown_city_without_routing_service_is_reported() -> None:
    with pytest.raises(UnknownLocationError) as error:
        provider().miles("Atlantis", "Miami")

    assert error.value.city == "Atlantis"


def test_broken_cache_does_not_fail_the_lookup() -> None:
    class BrokenCache(InMemoryDistanceCache):
        def get(self, a: str, b: str) -> Decimal | None:
            raise RuntimeError("database down")

    result = provider(BrokenCache(), FakeRouting(miles=Decimal("281.4"))).miles("Tampa", "Miami")

    assert result.source is DistanceSource.ORS


MCALLEN = City("McAllen", "TX", 26.2034, -98.2300)


def test_a_stored_city_keeps_its_spelling_whatever_the_case() -> None:
    distances = DistanceProvider(CITIES, TABLE, stored=InMemoryCityRepository([MCALLEN]))

    assert distances.normalize("mcallen") == "McAllen"
    assert distances.normalize("MCALLEN, tx") == "McAllen"
    assert distances.normalize("orlando") == "Orlando"  # the catalog still wins
    assert distances.normalize("springfield") == "Springfield"  # unknown everywhere: tidied as before


def test_a_stored_city_needs_no_geocoding_request() -> None:
    routing = FakeRouting(miles=Decimal("1386.0"))
    distances = DistanceProvider(CITIES, TABLE, routing=routing, stored=InMemoryCityRepository([MCALLEN]))

    result = distances.miles("Miami", "mcallen")

    assert (result.miles, result.source) == (Decimal("1386.0"), DistanceSource.ORS)
    assert routing.geocode_calls == []
    assert routing.route_calls == [((25.7617, -80.1918), (26.2034, -98.2300))]


def test_a_broken_city_table_falls_back_to_geocoding() -> None:
    routing = FakeRouting(geocodes={"Mcallen": (26.2, -98.2)})
    distances = DistanceProvider(CITIES, TABLE, routing=routing, stored=InMemoryCityRepository(fail=True))

    assert distances.normalize("mcallen") == "Mcallen"
    assert distances.miles("Miami", "mcallen").source is DistanceSource.ORS
    assert routing.geocode_calls == ["Mcallen"]
