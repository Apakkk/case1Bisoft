"""The case's distance table (config/distances.yaml), symmetric.

`FileDistanceTable` re-reads the file on the next lookup after it changes, so a pair added during a
demo applies without a restart. A broken edit keeps the last good table and says so; a broken file at
startup fails fast.
"""

import logging
from collections.abc import Callable, Iterable
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from app.clients.distance.cities import city_key

logger = logging.getLogger(__name__)

Canonical = Callable[[str], str | None]  # 'Ft Lauderdale' -> 'Fort Lauderdale'; None if unknown


class DistanceTableError(ValueError):
    """config/distances.yaml is not a list of [city, city, miles] rows."""


class StaticDistanceTable:
    problem: str | None = None  # a table built in memory is always the one meant

    def __init__(self, rows: Iterable[tuple[str, str, Decimal]]) -> None:
        self._miles = {frozenset({a, b}): miles for a, b, miles in rows}

    def lookup(self, a: str, b: str) -> Decimal | None:
        return self._miles.get(frozenset({a, b}))

    def city_names(self) -> set[str]:
        return {city for pair in self._miles for city in pair}


def parse_table(text: str, canonical: Canonical | None = None) -> StaticDistanceTable:
    """Validate and build the table. City names are written as the catalog spells them, if it knows them."""
    try:
        rows = yaml.safe_load(text) or []
    except yaml.YAMLError as error:
        raise DistanceTableError(f"not valid YAML: {error}") from error
    if not isinstance(rows, list):
        raise DistanceTableError("expected a list of [city, city, miles] rows")

    def name(raw: str) -> str:
        tidy = " ".join(raw.split())
        return (canonical(tidy) if canonical else None) or tidy

    table: dict[frozenset[str], tuple[str, str, Decimal]] = {}
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, list) or len(row) != 3:
            raise DistanceTableError(f"row {number}: expected [city, city, miles], got {row!r}")
        a, b, miles = row
        if not (isinstance(a, str) and isinstance(b, str) and a.strip() and b.strip()):
            raise DistanceTableError(f"row {number}: city names must be text")
        try:
            value = Decimal(str(miles))
        except InvalidOperation:
            value = Decimal(0)
        if isinstance(miles, bool) or not value.is_finite() or value <= 0:
            raise DistanceTableError(f"row {number}: miles must be a positive number, got {miles!r}")
        a, b = name(a), name(b)
        if city_key(a) == city_key(b):
            raise DistanceTableError(f"row {number}: {a} - {b} is one city")
        pair = frozenset({a, b})
        if pair in table and table[pair][2] != value:
            raise DistanceTableError(f"row {number}: {a} - {b} is listed twice with different miles")
        table[pair] = (a, b, value)
    return StaticDistanceTable(table.values())


def load_static_table(path: Path, canonical: Canonical | None = None) -> StaticDistanceTable:
    return parse_table(path.read_text(encoding="utf-8"), canonical)


class FileDistanceTable:
    """config/distances.yaml, re-read when the file changes."""

    def __init__(self, path: Path, canonical: Canonical | None = None) -> None:
        self._path = path
        self._canonical = canonical
        self._stamp = path.stat().st_mtime_ns
        self._table = load_static_table(path, canonical)  # raises: a broken file at startup is a config error
        self.problem: str | None = None  # Turkish warning while a broken edit is being ignored

    def lookup(self, a: str, b: str) -> Decimal | None:
        return self._current().lookup(a, b)

    def city_names(self) -> set[str]:
        return self._current().city_names()

    def _current(self) -> StaticDistanceTable:
        try:
            stamp = self._path.stat().st_mtime_ns
        except OSError as error:
            self.problem = f"{self._path.name} okunamadı ({error.strerror}); son geçerli mesafe tablosu kullanılıyor."
            return self._table
        if stamp != self._stamp:
            self._stamp = stamp
            try:
                self._table = load_static_table(self._path, self._canonical)
                self.problem = None
                logger.info("distance table reloaded: %s", self._path)
            except (DistanceTableError, OSError) as error:
                logger.warning("distance table %s ignored: %s", self._path, error)
                self.problem = f"{self._path.name} geçersiz ({error}); son geçerli mesafe tablosu kullanılıyor."
        return self._table
