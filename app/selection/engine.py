"""Filter -> rank. Pure functions over in-memory data."""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from decimal import Decimal

from app.models.carrier import Carrier
from app.models.order import Order
from app.selection.constraints import CONSTRAINTS
from app.selection.criteria import CRITERIA, REQUESTED, REQUESTED_KEY, SortKey
from app.selection.formatting import fmt_miles
from app.selection.money import total_cost
from app.selection.rules import RuleSet
from app.selection.types import Candidate, FilterResult, Rejection

DISTANCE_CONSTRAINT = "distance_range"


def filter_carriers(carriers: Iterable[Carrier], order: Order, route_miles: Decimal, rules: RuleSet) -> FilterResult:
    """Apply every hard constraint to every carrier and keep all reasons (not just the first)."""
    eligible: list[Candidate] = []
    rejected: list[Rejection] = []
    for carrier in carriers:
        reasons = tuple(
            reason for name in rules.filters if (reason := CONSTRAINTS[name](carrier, order, route_miles)) is not None
        )
        if reasons:
            rejected.append(Rejection(carrier.name, reasons))
        else:
            eligible.append(Candidate(carrier, total_cost(carrier.rate_per_mile, route_miles)))
    return FilterResult(tuple(eligible), tuple(rejected))


def distance_sensitive(
    carriers: Iterable[Carrier], order: Order, route_miles: Decimal, rules: RuleSet
) -> tuple[Carrier, ...]:
    """Carriers that pass every constraint except, possibly, the distance: only their limits can change the result."""
    others = [name for name in rules.filters if name != DISTANCE_CONSTRAINT]
    return tuple(c for c in carriers if all(CONSTRAINTS[name](c, order, route_miles) is None for name in others))


def needs_hq_distance(rules: RuleSet) -> bool:
    """HQ distances cost a lookup each; only fetch them when a criterion uses them."""
    return "hq_proximity" in rules.ranking


def with_requested(candidates: Iterable[Candidate], name: str | None) -> tuple[Candidate, ...]:
    return tuple(replace(c, requested=c.carrier.name == name) for c in candidates)


def with_hq_distances(
    candidates: Iterable[Candidate], distances: Mapping[str, Decimal | None]
) -> tuple[Candidate, ...]:
    """Attach HQ -> origin distances keyed by carrier name (supplied by the service layer)."""
    return tuple(replace(c, hq_distance=distances.get(c.carrier.name)) for c in candidates)


def sort_key(candidate: Candidate, rules: RuleSet) -> tuple[SortKey, ...]:
    return (REQUESTED.key(candidate), *(CRITERIA[name].key(candidate) for name in rules.ranking))


def rank(candidates: Iterable[Candidate], rules: RuleSet) -> tuple[Candidate, ...]:
    """A requested carrier first (always), then the rules lexicographically: later criteria only break
    exact ties of earlier ones."""
    return tuple(sorted(candidates, key=lambda c: sort_key(c, rules)))


def boundary_warnings(carriers: Iterable[Carrier], approx_miles: Decimal, ratio: Decimal) -> tuple[str, ...]:
    """Carrier limits within `ratio` of an approximate distance: the decision could flip with the real one."""
    warnings: list[str] = []
    for carrier in carriers:
        for limit, side in ((carrier.min_miles, "alt"), (carrier.max_miles, "üst")):
            if limit is not None and abs(approx_miles - limit) <= limit * ratio:
                warnings.append(
                    f"Yaklaşık mesafe ({fmt_miles(approx_miles)} mil) {carrier.name} {side} sınırına "
                    f"({fmt_miles(limit)} mil) yakın; gerçek mesafeyle karar değişebilir."
                )
    return tuple(warnings)


def deciding_criterion(first: Candidate, second: Candidate, rules: RuleSet) -> str | None:
    """The first criterion in priority order that separates two candidates (None = identical)."""
    if REQUESTED.key(first) != REQUESTED.key(second):
        return REQUESTED_KEY
    for name in rules.ranking:
        key = CRITERIA[name].key
        if key(first) != key(second):
            return name
    return None
