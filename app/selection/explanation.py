"""Turkish explanation built from the decision trace by templates. Jev never writes this text."""

from dataclasses import dataclass
from decimal import Decimal

from app.models.order import Order
from app.selection.criteria import CRITERIA
from app.selection.engine import deciding_criterion
from app.selection.formatting import fmt_miles, fmt_money, fmt_rate
from app.selection.rules import RuleSet
from app.selection.types import Candidate, Rejection


@dataclass(frozen=True, slots=True)
class Outcome:
    order: Order
    route_miles: Decimal
    distance_approximate: bool
    ranked: tuple[Candidate, ...]  # remaining eligible candidates, best first
    rejected: tuple[Rejection, ...]  # hard-constraint and carrier-note rejections
    selected: Candidate | None


def explain(outcome: Outcome, rules: RuleSet) -> str:
    parts = [_route(outcome)]
    if outcome.selected is None:
        parts.append("Uygun firma yok.")
    else:
        parts.append(_selection(outcome.selected, outcome.route_miles))
        parts.append(_why(outcome, rules))
    if outcome.rejected:
        rejected = ", ".join(f"{r.carrier_name} ({'; '.join(r.reasons)})" for r in outcome.rejected)
        parts.append(f"Elenenler: {rejected}.")
    return " ".join(parts)


def _route(o: Outcome) -> str:
    approx = " (yaklaşık)" if o.distance_approximate else ""
    order = o.order
    return (
        f"Rota {order.origin} → {order.destination}: {fmt_miles(o.route_miles)} mil{approx}; "
        f"{order.container_size} ft, {order.cargo_type}."
    )


def _selection(c: Candidate, miles: Decimal) -> str:
    return (
        f"{c.carrier.name} seçildi: toplam {fmt_money(c.total_cost)} "
        f"({fmt_miles(miles)} mil × {fmt_rate(c.carrier.rate_per_mile)}/mil)."
    )


def _why(o: Outcome, rules: RuleSet) -> str:
    assert o.selected is not None
    others = [c for c in o.ranked if c.carrier.name != o.selected.carrier.name]
    if not others:
        return "Tüm kısıtları sağlayan tek firma."
    runner_up = others[0]
    decided_by = deciding_criterion(o.selected, runner_up, rules)
    if decided_by is None:
        return f"{runner_up.carrier.name} ile tüm kriterler eşit."

    criterion = CRITERIA[decided_by]
    comparison = (
        f"{criterion.label} — {o.selected.carrier.name}: {criterion.describe(o.selected)}, "
        f"{runner_up.carrier.name}: {criterion.describe(runner_up)}."
    )
    equal = [CRITERIA[name].label for name in rules.ranking[: rules.ranking.index(decided_by)]]
    if not equal:
        return f"Belirleyici kriter: {comparison}"
    tied = ", ".join(equal)
    return f"{tied[0].upper()}{tied[1:]} eşit; belirleyici kriter: {comparison}"
