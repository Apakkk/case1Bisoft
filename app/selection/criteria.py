"""Ranking criteria. Lower sort key = better; rules.yaml `ranking` sets their priority order.

Adding a criterion = one Criterion entry + its name in rules.yaml (return a negated value for
"higher is better" attributes such as a rating).
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.selection.formatting import fmt_miles, fmt_money
from app.selection.types import Candidate

SortKey = tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Criterion:
    key: Callable[[Candidate], SortKey]
    label: str  # Turkish, used in explanations
    describe: Callable[[Candidate], str]  # the candidate's value, for explanations


def _hq_key(c: Candidate) -> SortKey:
    # Unknown distances sort after every known one.
    return (c.hq_distance is None, c.hq_distance if c.hq_distance is not None else Decimal(0))


def _hq_describe(c: Candidate) -> str:
    if c.hq_distance is None:
        return f"bilinmiyor ({c.carrier.hq_city})"
    return f"{fmt_miles(c.hq_distance)} mil ({c.carrier.hq_city})"


CRITERIA: dict[str, Criterion] = {
    "total_cost": Criterion(
        key=lambda c: (c.total_cost,),
        label="toplam ücret",
        describe=lambda c: fmt_money(c.total_cost),
    ),
    "hq_proximity": Criterion(
        key=_hq_key,
        label="merkezin çıkış noktasına uzaklığı",
        describe=_hq_describe,
    ),
    "name": Criterion(
        key=lambda c: (c.carrier.name.casefold(),),
        label="firma adı",
        describe=lambda c: c.carrier.name,
    ),
}
