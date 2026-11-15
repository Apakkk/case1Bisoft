"""The case's distance table (config/distances.yaml), symmetric."""

from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

import yaml


class StaticDistanceTable:
    def __init__(self, rows: Iterable[tuple[str, str, Decimal]]) -> None:
        self._miles = {frozenset({a, b}): miles for a, b, miles in rows}

    def lookup(self, a: str, b: str) -> Decimal | None:
        return self._miles.get(frozenset({a, b}))

    def city_names(self) -> set[str]:
        return {city for pair in self._miles for city in pair}


def load_static_table(path: Path) -> StaticDistanceTable:
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return StaticDistanceTable((str(a), str(b), Decimal(str(m))) for a, b, m in rows)
