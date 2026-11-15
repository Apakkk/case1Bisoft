"""Distance chain and city resolution.

Distance: same city -> case table -> cache -> OpenRouteService -> Haversine x factor. The case table always
wins: its pairs never reach the routing service, so Miami - Orlando is 235 miles whatever a map says. A pair
outside the table is asked once and stored, so it stays the same afterwards.

City resolution (`normalize`): US cities only, never a guess. A name is a catalog city or alias, a shipped
US city (us_cities.csv), a city found earlier (`cities` table), or a US locality OpenRouteService confirms
by exactly that name. Anything else raises UnknownLocationError with "did you mean" suggestions.

Distances are never estimated by a model. Only the Haversine tier is approximate, and it says so.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.clients.distance.cities import CityDirectory, Coordinates, city_key, split_qualifier, state_code
from app.clients.distance.haversine import haversine_miles
from app.clients.distance.ors import RoutingClient, RoutingError
from app.models.city import City, Place

logger = logging.getLogger(__name__)

TENTH = Decimal("0.1")
ROUTING_FAILED = "Harita servisi kullanılamadı; mesafe yaklaşık hesaplandı."


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


class LocationProblem(StrEnum):
    NOT_FOUND = "not_found"  # no US city by this name (suggestions: similar spellings)
    OUTSIDE_US = "outside_us"  # 'Amsterdam, Netherlands' (suggestion: the US city of that name, if any)
    OTHER_STATE = "other_state"  # 'Portland, ME' while Portland is known as Portland, OR
    UNVERIFIED = "unverified"  # not a known city, and the routing service could not confirm it


class UnknownLocationError(Exception):
    """Not a US city the system can locate. Carries what to tell the user instead of a guess."""

    def __init__(
        self,
        city: str,
        problem: LocationProblem = LocationProblem.NOT_FOUND,
        suggestions: Sequence[Place] = (),
        qualifier: str = "",
    ) -> None:
        self.city = city
        self.problem = problem
        self.suggestions = tuple(suggestions)
        self.qualifier = qualifier  # what followed the comma, for OUTSIDE_US
        super().__init__(self.detail)

    @property
    def detail(self) -> str:
        """English, for API error bodies."""
        hint = ", ".join(place.label for place in self.suggestions)
        if self.problem is LocationProblem.OUTSIDE_US:
            text = f"only US cities are supported; '{self.qualifier}' is not a US state"
            return f"{text} (US city with this name: {hint})" if hint else text
        if self.problem is LocationProblem.OTHER_STATE:
            return f"{self.city}: cities are known by name, and this name is {hint}"
        if self.problem is LocationProblem.UNVERIFIED:
            text = f"location not in the known cities and the map service could not confirm it: {self.city}"
        else:
            text = f"location not found: {self.city}"
        return f"{text} (did you mean: {hint}?)" if hint else text

    @property
    def message(self) -> str:
        """Turkish, for the screens."""
        hint = ", ".join(place.label for place in self.suggestions)
        if self.problem is LocationProblem.OUTSIDE_US:
            text = f"Yalnızca ABD şehirleri destekleniyor; '{self.qualifier}' bir ABD eyaleti değil."
            return f"{text} ABD'de bu adla: {hint}." if hint else text
        if self.problem is LocationProblem.OTHER_STATE:
            return f"'{self.city}' tanınmıyor: şehirler adıyla tanınır ve bu ad {hint} olarak kayıtlı."
        if self.problem is LocationProblem.UNVERIFIED:
            text = f"'{self.city}' kayıtlı şehirler arasında yok ve harita servisine ulaşılamadığı için doğrulanamadı."
        else:
            text = f"'{self.city}' adında bir ABD şehri bulunamadı."
        return f"{text} Bunu mu demek istediniz: {hint}?" if hint else text


class DistanceTable(Protocol):
    def lookup(self, a: str, b: str) -> Decimal | None: ...

    @property
    def problem(self) -> str | None: ...  # Turkish warning when a broken edit is being ignored


class DistanceCache(Protocol):
    def get(self, a: str, b: str) -> Decimal | None: ...
    def put(self, a: str, b: str, miles: Decimal, source: str) -> None: ...


class StoredCities(Protocol):
    """Cities found earlier through the routing service (the `cities` table)."""

    def find(self, name: str) -> City | None: ...
    def add(self, cities: Sequence[City]) -> None: ...


class DistanceProvider:
    def __init__(
        self,
        cities: CityDirectory,
        table: DistanceTable,
        cache: DistanceCache | None = None,
        routing: RoutingClient | None = None,
        stored: StoredCities | None = None,
    ) -> None:
        self._cities = cities
        self._table = table
        self._cache = cache
        self._routing = routing
        self._stored = stored
        self._found: dict[str, City] = {}  # name -> city located outside the shipped files, this run
        self._asked: dict[tuple[str, str | None], City | None] = {}  # ORS answers: (key, state) -> city or none

    # --- cities -------------------------------------------------------------------------------

    def normalize(self, city: str) -> str:
        """The canonical name of the US city meant by `city`; UnknownLocationError if there is none.

        'ft. lauderdale' -> 'Fort Lauderdale', 'MIAMI, Florida' -> 'Miami', 'mcallen' -> 'McAllen' (stored, or
        confirmed by ORS once). A state after a comma must be the city's state; anything else is refused.
        """
        raw = " ".join(city.split())
        name, qualifier = split_qualifier(raw)
        if not name:
            raise UnknownLocationError(raw)
        state = None
        if qualifier is not None:
            state = state_code(qualifier)
            if state is None:
                same_name = self._cities.lookup(name)
                suggestions = [self._cities.place(same_name)] if same_name else []
                raise UnknownLocationError(raw, LocationProblem.OUTSIDE_US, suggestions, qualifier)

        known = self._cities.lookup(name)
        if known is not None:
            return self._in_state(raw, self._cities.place(known), state)
        stored = self._find_stored(name)
        if stored is not None:
            self._found[stored.name] = stored
            return self._in_state(raw, Place(stored.name, stored.state), state)
        return self._confirm_online(raw, name, state)

    def state_of(self, city: str) -> str:
        """Two-letter state of a city returned by `normalize` ('' if unknown)."""
        found = self._found.get(city)
        return found.state if found is not None else self._cities.state_of(city)

    def _in_state(self, raw: str, place: Place, state: str | None) -> str:
        if state is not None and place.state and place.state != state:
            raise UnknownLocationError(raw, LocationProblem.OTHER_STATE, [place])
        return place.name

    def _confirm_online(self, raw: str, name: str, state: str | None) -> str:
        """A US locality ORS knows by exactly this name (and state); stored, so it is local from then on."""
        key = city_key(name)
        if (key, state) not in self._asked:
            if self._routing is None:
                raise UnknownLocationError(raw, LocationProblem.UNVERIFIED, self._cities.close_matches(name))
            text = self._cities.normalize(name)  # 'marfa' -> 'Marfa'
            try:
                candidates = self._routing.geocode(f"{text}, {state}" if state else text)
            except RoutingError as error:  # not remembered: the next quote tries again
                logger.warning("geocoding failed for %s: %s", raw, error)
                raise UnknownLocationError(raw, LocationProblem.UNVERIFIED, self._cities.close_matches(name)) from error
            match = next(
                (c for c in candidates if city_key(c.name) == key and state in (None, c.state)),
                None,
            )
            self._asked[(key, state)] = match
            if match is not None:
                self._remember(match)
        found = self._asked[(key, state)]
        if found is None:
            raise UnknownLocationError(raw, LocationProblem.NOT_FOUND, self._cities.close_matches(name))
        return found.name

    def _remember(self, city: City) -> None:
        self._found[city.name] = city
        if self._stored is None:
            return
        try:
            self._stored.add([city])
        except Exception:  # the city still works for this run
            logger.exception("city table write failed")

    def _find_stored(self, city: str) -> City | None:
        if self._stored is None:
            return None
        try:
            return self._stored.find(city)
        except Exception:  # a broken table must never fail a quote; ORS can still confirm the city
            logger.exception("city table read failed")
            return None

    # --- distances ----------------------------------------------------------------------------

    def miles(self, a: str, b: str, *, approximate_factor: Decimal = Decimal("1.2")) -> DistanceResult:
        a, b = self.normalize(a), self.normalize(b)
        if a == b:
            return DistanceResult(Decimal(0), DistanceSource.SAME_CITY)

        table_miles = self._table.lookup(a, b)
        notes = (self._table.problem,) if self._table.problem else ()
        if table_miles is not None:
            return DistanceResult(table_miles, DistanceSource.CASE_TABLE, notes)

        cached = self._cache_get(a, b)
        if cached is not None:
            return DistanceResult(cached, DistanceSource.CACHE, notes)

        warnings = notes
        if self._routing is not None:
            try:
                return replace(self._route(a, b), warnings=notes)
            except RoutingError as error:
                logger.warning("routing failed for %s - %s: %s", a, b, error)
                warnings = (*notes, ROUTING_FAILED)

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
        """Every name `normalize` returns has coordinates: shipped files, or a city located this run."""
        known = self._cities.coordinates_of(city)
        if known is not None:
            return known
        found = self._found.get(city)
        if found is None:
            raise UnknownLocationError(city)
        return (found.lat, found.lon)

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
