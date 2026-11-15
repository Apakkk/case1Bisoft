"""The case's carriers, distance table and seven test orders, plus a pure pipeline helper.

`decide()` mirrors what QuoteService does (filter -> HQ distances -> rank) without any I/O.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models.carrier import Carrier
from app.models.order import Order
from app.selection.engine import filter_carriers, needs_hq_distance, rank, with_hq_distances
from app.selection.rules import RuleSet, parse_rules
from app.selection.types import Candidate, Rejection

D = Decimal

S_LOGISTICS = Carrier("S-Logistics", "Tampa", None, D("300"), frozenset({40, 45}), frozenset({"Dry"}), D("0.40"))
B_LOGISTICS = Carrier(
    "B-Logistics", "Fort Lauderdale", D("250"), None, frozenset({20}), frozenset({"Dry", "Reefer"}), D("1.00")
)
A_LOGISTICS = Carrier(
    "A-Logistics", "Jacksonville", None, D("200"), frozenset({45}), frozenset({"Dry", "Hazardous"}), D("2.00")
)
M_LOGISTICS = Carrier(
    "M-Logistics", "Houston", None, None, frozenset({20, 40}), frozenset({"Dry", "Reefer", "Hazardous"}), D("1.00")
)
CASE_CARRIERS = (S_LOGISTICS, B_LOGISTICS, A_LOGISTICS, M_LOGISTICS)

CASE_DISTANCES = {
    frozenset({"Miami", "Fort Lauderdale"}): D("30"),
    frozenset({"Miami", "Orlando"}): D("235"),
    frozenset({"Miami", "Atlanta"}): D("660"),
    frozenset({"Jacksonville", "Savannah"}): D("140"),
    frozenset({"Tampa", "Jacksonville"}): D("200"),
    frozenset({"Miami", "Houston"}): D("1190"),
    frozenset({"Tampa", "Orlando"}): D("85"),
}

DEFAULT_RULES_DATA: dict[str, Any] = {
    "filters": ["distance_range", "container_size", "cargo_type"],
    "ranking": ["total_cost", "hq_proximity", "name"],
    "catalog": {"cargo_types": ["Dry", "Reefer", "Hazardous"], "container_sizes": [20, 40, 45]},
    "confidence": {"auto_accept": 0.85, "needs_review": 0.60, "hazardous_review": 0.15},
    "distance": {"approximate_factor": 1.2, "boundary_warning_ratio": 0.10},
}


def default_rules(**overrides: Any) -> RuleSet:
    return parse_rules({**DEFAULT_RULES_DATA, **overrides})


def case_distance(a: str, b: str) -> Decimal | None:
    if a == b:
        return D("0")
    return CASE_DISTANCES.get(frozenset({a, b}))


@dataclass(frozen=True)
class CaseOrder:
    id: int
    order: Order
    expected_carrier: str | None
    expected_cost: Decimal | None


CASE_ORDERS = (
    CaseOrder(1, Order("Miami", "Fort Lauderdale", 40, "Reefer"), "M-Logistics", D("30.00")),
    CaseOrder(2, Order("Miami", "Orlando", 40, "Dry"), "S-Logistics", D("94.00")),
    CaseOrder(3, Order("Miami", "Atlanta", 20, "Reefer"), "B-Logistics", D("660.00")),
    CaseOrder(4, Order("Jacksonville", "Savannah", 45, "Hazardous"), "A-Logistics", D("280.00")),
    CaseOrder(5, Order("Tampa", "Jacksonville", 45, "Dry"), "S-Logistics", D("80.00")),
    CaseOrder(6, Order("Miami", "Houston", 45, "Reefer"), None, None),
    CaseOrder(7, Order("Tampa", "Orlando", 20, "Hazardous"), "M-Logistics", D("85.00")),
)


@dataclass(frozen=True)
class Decided:
    ranked: tuple[Candidate, ...]
    rejected: tuple[Rejection, ...]
    route_miles: Decimal

    @property
    def winner(self) -> Candidate | None:
        return self.ranked[0] if self.ranked else None


def decide(
    order: Order,
    *,
    carriers: Iterable[Carrier] = CASE_CARRIERS,
    rules: RuleSet | None = None,
    route_miles: Decimal | None = None,
    hq_distance: Callable[[str, str], Decimal | None] = case_distance,
) -> Decided:
    rules = rules or default_rules()
    miles = route_miles if route_miles is not None else case_distance(order.origin, order.destination)
    assert miles is not None, f"no distance for {order.origin} -> {order.destination}"
    result = filter_carriers(carriers, order, miles, rules)
    candidates = result.eligible
    if needs_hq_distance(rules):
        distances = {c.carrier.name: hq_distance(c.carrier.hq_city, order.origin) for c in candidates}
        candidates = with_hq_distances(candidates, distances)
    return Decided(rank(candidates, rules), result.rejected, miles)
