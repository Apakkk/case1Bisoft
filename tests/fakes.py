"""In-memory fakes injected instead of PostgreSQL, OpenRouteService and Jev (no mock patching)."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from app.clients.distance.chain import DistanceProvider
from app.clients.distance.cities import Coordinates, load_city_directory
from app.clients.distance.ors import RoutingError
from app.clients.distance.static_table import load_static_table
from app.clients.jev_client import (
    ChoiceResult,
    JevUnavailableError,
    NotePrecheck,
    NotesCheck,
    OrderClassification,
)
from app.models.carrier import Carrier
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
    """Scripted routing client that records calls; `fail=True` simulates an outage."""

    def __init__(
        self,
        *,
        miles: Decimal = Decimal("100.0"),
        geocodes: dict[str, Coordinates] | None = None,
        fail: bool = False,
    ) -> None:
        self.miles = miles
        self.geocodes = geocodes or {}
        self.fail = fail
        self.route_calls: list[tuple[Coordinates, Coordinates]] = []
        self.geocode_calls: list[str] = []

    def geocode(self, city: str) -> Coordinates | None:
        self.geocode_calls.append(city)
        if self.fail:
            raise RoutingError("simulated outage")
        return self.geocodes.get(city)

    def driving_miles(self, origin: Coordinates, destination: Coordinates) -> Decimal:
        self.route_calls.append((origin, destination))
        if self.fail:
            raise RoutingError("simulated outage")
        return self.miles


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
    table = load_static_table(Path("config/distances.yaml"))
    cities = load_city_directory(Path("config/cities.csv"), Path("config/city_aliases.yaml"), table.city_names())
    return DistanceProvider(cities, table, cache, routing)


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
        restriction: float = 0.0,
        fail: bool = False,
    ) -> None:
        self.cargo, self.size, self.blocks = cargo, size, blocks or {}
        self.restriction, self.fail = restriction, fail
        self.calls: list[str] = []
        self.notes_asked: list[dict[str, str]] = []

    def classify_order(
        self, text: str, cargo_types: Sequence[str] | None, container_sizes: Sequence[int] | None
    ) -> OrderClassification:
        self._record("classify_order")
        return OrderClassification(self.cargo if cargo_types else None, self.size if container_sizes else None, 7)

    def notes_block_order(self, order: Order, notes: Mapping[str, str]) -> NotesCheck:
        self._record("notes_block_order")
        self.notes_asked.append(dict(notes))
        return NotesCheck({name: self.blocks.get(name, 0.0) for name in notes}, 9)

    def note_has_restriction(self, note: str) -> NotePrecheck:
        self._record("note_has_restriction")
        return NotePrecheck(self.restriction, 5)

    def _record(self, method: str) -> None:
        self.calls.append(method)
        if self.fail:
            raise JevUnavailableError("simulated outage")
