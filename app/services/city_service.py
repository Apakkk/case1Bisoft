"""City suggestions for the city inputs and GET /api/v1/cities: local first, OpenRouteService only when needed.

Local = the shipped cities (catalog + aliases, and ~5,100 US cities with 5,000+ people) and the `cities`
table. ORS autocomplete is asked only when nothing local matches (a small town); whatever it returns is
stored, so the next time the same city comes from the database. ORS has a daily quota, hence the guards in
`_worth_asking`.
"""

import logging
import time
from collections.abc import Callable, Iterable

from app.clients.distance.cities import CityDirectory, CityEntry, city_key, rank_suggestions
from app.clients.distance.ors import AUTOCOMPLETE_PAGE_SIZE, PlaceSearch, RoutingError
from app.models.city import City, CitySource, CitySuggestions
from app.repositories.city_repository import CityRepository

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 5
MAX_LIMIT = 10
MIN_ONLINE_CHARS = 3  # one or two letters match too much to be worth a quota-limited request
OUTAGE_PAUSE_SECONDS = 60.0  # after a failure, do not hammer the service on every keystroke
_MAX_REMEMBERED_QUERIES = 10_000

ONLINE_FAILED = "Harita servisine ulaşılamadı; yalnızca kayıtlı şehirler gösteriliyor."
ONLINE_DISABLED = "Harita servisi kapalı (ORS anahtarı yok); yalnızca kayıtlı şehirler gösteriliyor."


class CityService:
    def __init__(
        self,
        directory: CityDirectory,
        repository: CityRepository | None = None,
        places: PlaceSearch | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._directory = directory
        self._repository = repository
        self._places = places
        self._clock = clock
        self._asked: set[str] = set()  # query keys already sent to ORS
        self._complete: set[str] = set()  # query keys whose ORS answer was the whole list
        self._paused_until = 0.0

    def suggest(self, query: str, limit: int = DEFAULT_LIMIT) -> CitySuggestions:
        name_part = query.partition(",")[0].strip()
        key = city_key(name_part)
        if not key:
            return CitySuggestions([])

        stored = self._stored(key)
        entries = [*self._directory.entries(), *self._entries(stored)]
        ranked = rank_suggestions(query, entries, limit)
        if ranked or not self._worth_asking(key):
            return CitySuggestions(ranked)
        if self._places is None:
            return CitySuggestions(ranked, (ONLINE_DISABLED,))
        if self._clock() < self._paused_until:
            return CitySuggestions(ranked, (ONLINE_FAILED,))

        try:
            found = self._places.autocomplete(name_part)
        except RoutingError as error:
            logger.warning("city autocomplete failed for %r: %s", name_part, error)
            self._paused_until = self._clock() + OUTAGE_PAUSE_SECONDS
            return CitySuggestions(ranked, (ONLINE_FAILED,))

        self._remember(key, complete=len(found) < AUTOCOMPLETE_PAGE_SIZE)
        new = self._new_cities(found)
        self._save(new)
        return CitySuggestions(rank_suggestions(query, [*entries, *self._entries(new, start=len(stored))], limit))

    def _worth_asking(self, key: str) -> bool:
        if len(key) < MIN_ONLINE_CHARS or key in self._asked:
            return False
        # 'orl' came back complete -> 'orla', 'orlan', ... can only be a subset of what is already stored.
        return not any(key[:n] in self._complete for n in range(MIN_ONLINE_CHARS, len(key)))

    def _remember(self, key: str, *, complete: bool) -> None:
        if len(self._asked) >= _MAX_REMEMBERED_QUERIES:
            self._asked.clear()
            self._complete.clear()
        self._asked.add(key)
        if complete:
            self._complete.add(key)

    def _new_cities(self, found: Iterable[City]) -> list[City]:
        """Drop catalog cities (they already have coordinates) and repeated names (first one wins)."""
        seen: set[str] = set()
        new = []
        for city in found:
            key = city_key(city.name)
            if not key or key in seen or self._directory.lookup(city.name) is not None:
                continue
            seen.add(key)
            new.append(city)
        return new

    def _stored(self, key: str) -> list[City]:
        if self._repository is None:
            return []
        try:
            return self._repository.search(key)
        except Exception:  # a broken table must never break typing a city name
            logger.exception("city table read failed")
            return []

    def _save(self, cities: list[City]) -> None:
        if self._repository is None or not cities:
            return
        try:
            self._repository.add(cities)
        except Exception:
            logger.exception("city table write failed")

    @staticmethod
    def _entries(cities: Iterable[City], start: int = 0) -> list[CityEntry]:
        """Stored rows come in insertion order = the order ORS ranked them when they were first found."""
        return [CityEntry.of(city, CitySource.ORS, rank) for rank, city in enumerate(cities, start)]
