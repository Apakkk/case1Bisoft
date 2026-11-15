"""In-memory fakes injected instead of PostgreSQL, OpenRouteService and Jev (no mock patching)."""

import functools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from app.clients.distance.chain import DistanceProvider
from app.clients.distance.cities import CityDirectory, Coordinates, city_key, match_tier
from app.clients.distance.ors import RoutingError
from app.clients.distance.static_table import FileDistanceTable
from app.clients.jev_client import (
    NO_REQUEST,
    ChoiceResult,
    CompatibilityCheck,
    JevUnavailableError,
    NotePrecheck,
    OrderClassification,
)
from app.dependencies import load_distance_config
from app.models.carrier import Carrier
from app.models.city import City
from app.models.order import Order
from app.repositories.carrier_repository import DuplicateCarrierError
from app.selection.rules import RuleSet


class InMemoryDistanceCache:
    def __init__(self) -> None:
        self.rows: dict[frozenset[str], Decimal] = {}

    def get(self, a: str, b: str) -> Decimal | None:
        return self.rows.get(frozenset({a, b}))

    def put(self, a: str, b: str, miles: Decimal, source: str) -> None:
        self.rows[frozenset({a, b})] = miles


class FakeRouting:
    """Scripted routing client that records calls; `fail=True` simulates an outage.

    `places`: what geocoding returns for a text, in ORS order (look-alikes included, like Pelias).
    """

    def __init__(
        self,
        *,
        miles: Decimal = Decimal("100.0"),
        places: dict[str, list[City]] | None = None,
        fail: bool = False,
    ) -> None:
        self.miles = miles
        self.places = places or {}
        self.fail = fail
        self.route_calls: list[tuple[Coordinates, Coordinates]] = []
        self.geocode_calls: list[str] = []

    def geocode(self, text: str) -> list[City]:
        self.geocode_calls.append(text)
        if self.fail:
            raise RoutingError("simulated outage")
        return list(self.places.get(text, []))

    def driving_miles(self, origin: Coordinates, destination: Coordinates) -> Decimal:
        self.route_calls.append((origin, destination))
        if self.fail:
            raise RoutingError("simulated outage")
        return self.miles


class InMemoryCityRepository:
    """Behaves like PostgresCityRepository: prefix/word-start search, case-insensitive find, first row wins."""

    def __init__(self, cities: Iterable[City] = (), *, fail: bool = False) -> None:
        self.rows: dict[str, City] = {}
        for city in cities:
            self.rows.setdefault(city_key(city.name), city)
        self.fail = fail
        self.find_calls: list[str] = []

    def search(self, query_key: str, limit: int = 50) -> list[City]:
        if self.fail:
            raise RuntimeError("simulated database outage")
        tiers = {key: match_tier(key, query_key) for key in self.rows}
        matching = [key for key, tier in tiers.items() if tier is not None]
        return [self.rows[key] for key in sorted(matching, key=lambda k: tiers[k] or 0)][:limit]

    def find(self, name: str) -> City | None:
        self.find_calls.append(name)
        if self.fail:
            raise RuntimeError("simulated database outage")
        return self.rows.get(city_key(name))

    def add(self, cities: Sequence[City]) -> None:
        if self.fail:
            raise RuntimeError("simulated database outage")
        for city in cities:
            self.rows.setdefault(city_key(city.name), city)


class FakePlaces:
    """Scripted ORS autocomplete: returns the configured cities that match the text, records every call."""

    def __init__(self, cities: Iterable[City] = (), *, fail: bool = False) -> None:
        self.cities = list(cities)
        self.fail = fail
        self.calls: list[str] = []

    def autocomplete(self, text: str) -> list[City]:
        self.calls.append(text)
        if self.fail:
            raise RoutingError("simulated outage")
        return [c for c in self.cities if match_tier(city_key(c.name), city_key(text)) is not None]


class InMemoryCarrierRepository:
    """Behaves like PostgresCarrierRepository (ids, case-insensitive unique names, name ordering)."""

    def __init__(self, carriers: Iterable[Carrier] = ()) -> None:
        self._rows: dict[int, Carrier] = {}
        self._next_id = 1
        for carrier in carriers:
            self.create(carrier)

    def list(self) -> list[Carrier]:
        return sorted(self._rows.values(), key=lambda c: c.name.casefold())

    def get(self, carrier_id: int) -> Carrier | None:
        return self._rows.get(carrier_id)

    def create(self, carrier: Carrier) -> Carrier:
        self._check_unique(carrier.name, exclude=None)
        stored = replace(carrier, id=self._next_id)
        self._rows[self._next_id] = stored
        self._next_id += 1
        return stored

    def update(self, carrier_id: int, carrier: Carrier) -> Carrier | None:
        if carrier_id not in self._rows:
            return None
        self._check_unique(carrier.name, exclude=carrier_id)
        self._rows[carrier_id] = replace(carrier, id=carrier_id)
        return self._rows[carrier_id]

    def delete(self, carrier_id: int) -> bool:
        return self._rows.pop(carrier_id, None) is not None

    def _check_unique(self, name: str, exclude: int | None) -> None:
        if any(c.name.casefold() == name.casefold() and i != exclude for i, c in self._rows.items()):
            raise DuplicateCarrierError(name)


class StaticRules:
    def __init__(self, rules: RuleSet) -> None:
        self.rules = rules

    def get(self) -> RuleSet:
        return self.rules


def offline_distances(
    cache: InMemoryDistanceCache | None = None, routing: FakeRouting | None = None
) -> DistanceProvider:
    """The real distance chain over the shipped config files, with no database and no network."""
    table, cities = shipped_distance_config()
    return DistanceProvider(cities, table, cache, routing)


@functools.cache
def shipped_distance_config() -> tuple[FileDistanceTable, CityDirectory]:
    """config/ loaded once per test run (~5,100 US cities); every provider still starts with its own memory."""
    return load_distance_config(Path("config"))


def choice(label: str, confidence: float, **probabilities: float) -> ChoiceResult:
    return ChoiceResult(label, confidence, probabilities or {label: confidence})


class FakeJev:
    """Scripted Jev: returns configured answers and records every call (tokens are never spent in tests)."""

    def __init__(
        self,
        *,
        cargo: ChoiceResult | None = None,
        size: ChoiceResult | None = None,
        blocks: dict[str, float] | None = None,
        requested: ChoiceResult | None = None,
        restriction: float = 0.0,
        fail: bool = False,
    ) -> None:
        self.cargo, self.size, self.blocks = cargo, size, blocks or {}
        self.requested = requested or ChoiceResult(NO_REQUEST, 0.97, {NO_REQUEST: 0.97})
        self.requestable: list[list[str]] = []  # carrier names offered per compatibility request
        self.restriction, self.fail = restriction, fail
        self.calls: list[str] = []
        self.notes_asked: list[dict[str, str]] = []  # carrier descriptions per compatibility request
        self.order_notes: list[str] = []  # order note per compatibility request

    def classify_order(
        self, text: str, cargo_types: Sequence[str] | None, container_sizes: Sequence[int] | None
    ) -> OrderClassification:
        self._record("classify_order")
        return OrderClassification(self.cargo if cargo_types else None, self.size if container_sizes else None, 7)

    def check_compatibility(
        self, order: Order, order_note: str, carrier_notes: Mapping[str, str], requestable: Sequence[str] = ()
    ) -> CompatibilityCheck:
        self._record("check_compatibility")
        self.notes_asked.append(dict(carrier_notes))
        self.order_notes.append(order_note)
        self.requestable.append(list(requestable))
        conflicts = {name: self.blocks.get(name, 0.0) for name in carrier_notes}
        return CompatibilityCheck(conflicts, 9, self.requested if order_note and requestable else None)

    def note_has_restriction(self, note: str) -> NotePrecheck:
        self._record("note_has_restriction")
        return NotePrecheck(self.restriction, 5)

    def _record(self, method: str) -> None:
        self.calls.append(method)
        if self.fail:
            raise JevUnavailableError("simulated outage")
