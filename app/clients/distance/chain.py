"""Distance chain: same city -> case table -> cache -> OpenRouteService -> Haversine x factor.

Distances are never estimated by a model. Only the Haversine tier is approximate, and it says so.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.clients.distance.cities import CityDirectory, Coordinates
from app.clients.distance.haversine import haversine_miles
from app.clients.distance.ors import RoutingClient, RoutingError
from app.clients.distance.static_table import StaticDistanceTable

logger = logging.getLogger(__name__)

TENTH = Decimal("0.1")


class DistanceSource(StrEnum):
    SAME_CITY = "same_city"
    CASE_TABLE = "case_table"
    CACHE = "cache"
    ORS = "ors"
    HAVERSINE = "haversine"


@dataclass(frozen=True, slots=True)
class DistanceResult:
    miles: Decimal
    source: DistanceSource
    warnings: tuple[str, ...] = ()

    @property
    def approximate(self) -> bool:
        return self.source is DistanceSource.HAVERSINE


class UnknownLocationError(Exception):
    def __init__(self, city: str) -> None:
        super().__init__(f"unknown location: {city}")
        self.city = city


class DistanceCache(Protocol):
    def get(self, a: str, b: str) -> Decimal | None: ...
    def put(self, a: str, b: str, miles: Decimal, source: str) -> None: ...


class DistanceProvider:
    def __init__(
        self,
        cities: CityDirectory,
        table: StaticDistanceTable,
        cache: DistanceCache | None = None,
        routing: RoutingClient | None = None,
    ) -> None:
        self._cities = cities
        self._table = table
        self._cache = cache
        self._routing = routing
        self._geocoded: dict[str, Coordinates | None] = {}

    def normalize(self, city: str) -> str:
        return self._cities.normalize(city)

    def miles(self, a: str, b: str, *, approximate_factor: Decimal = Decimal("1.2")) -> DistanceResult:
        a, b = self.normalize(a), self.normalize(b)
        if a == b:
            return DistanceResult(Decimal(0), DistanceSource.SAME_CITY)

        table_miles = self._table.lookup(a, b)
        if table_miles is not None:
            return DistanceResult(table_miles, DistanceSource.CASE_TABLE)

        cached = self._cache_get(a, b)
        if cached is not None:
            return DistanceResult(cached, DistanceSource.CACHE)

        warnings: tuple[str, ...] = ()
        if self._routing is not None:
            try:
                return self._route(a, b)
            except RoutingError as error:
                logger.warning("routing failed for %s - %s: %s", a, b, error)
                warnings = ("Harita servisi kullanılamadı; mesafe yaklaşık hesaplandı.",)

        origin, destination = self._coordinates(a), self._coordinates(b)
        straight = haversine_miles(origin, destination)
        miles = (Decimal(str(straight)) * approximate_factor).quantize(TENTH)
        return DistanceResult(miles, DistanceSource.HAVERSINE, warnings)

    def _route(self, a: str, b: str) -> DistanceResult:
        assert self._routing is not None
        miles = self._routing.driving_miles(self._coordinates(a), self._coordinates(b))
        self._cache_put(a, b, miles)
        return DistanceResult(miles, DistanceSource.ORS)

    def _coordinates(self, city: str) -> Coordinates:
        known = self._cities.coordinates_of(city)
        if known is not None:
            return known
        if city not in self._geocoded:
            self._geocoded[city] = self._geocode(city)
        found = self._geocoded[city]
        if found is None:
            raise UnknownLocationError(city)
        return found

    def _geocode(self, city: str) -> Coordinates | None:
        if self._routing is None:
            return None
        try:
            return self._routing.geocode(city)
        except RoutingError as error:
            logger.warning("geocoding failed for %s: %s", city, error)
            return None

    def _cache_get(self, a: str, b: str) -> Decimal | None:
        if self._cache is None:
            return None
        try:
            return self._cache.get(a, b)
        except Exception:  # a broken cache must never fail a quote
            logger.exception("distance cache read failed")
            return None

    def _cache_put(self, a: str, b: str, miles: Decimal) -> None:
        if self._cache is None:
            return
        try:
            self._cache.put(a, b, miles, DistanceSource.ORS.value)
        except Exception:
            logger.exception("distance cache write failed")
