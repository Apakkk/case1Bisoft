"""Turkish explanation built from the decision trace by templates. Jev never writes this text."""

from dataclasses import dataclass
from decimal import Decimal

from app.models.order import Order
from app.selection.criteria import CRITERIA, REQUESTED, REQUESTED_KEY
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
    rejected: tuple[Rejection, ...]  # hard-constraint and free-text (Jev) rejections
    selected: Candidate | None
    requested: str | None = None  # carrier the order description asks for (Jev), if any


def explain(outcome: Outcome, rules: RuleSet) -> str:
    parts = [_route(outcome)]
    request_note = _requested_unavailable(outcome)
    if request_note:
        parts.append(request_note)
    if outcome.selected is None:
        parts.append("Uygun firma yok.")
    else:
        parts.append(_selection(outcome.selected, outcome.route_miles))
        parts.append(_why(outcome, rules))
    # The requested carrier's reasons are already in request_note.
    others = [r for r in outcome.rejected if not (request_note and r.carrier_name == outcome.requested)]
    if others:
        rejected = ", ".join(f"{r.carrier_name} ({'; '.join(r.reasons)})" for r in others)
        parts.append(f"Elenenler: {rejected}.")
    return " ".join(parts)


def _requested_unavailable(o: Outcome) -> str | None:
    """The order asked for a carrier that is not selected: say why, before naming the fallback."""
    if o.requested is None or (o.selected is not None and o.selected.carrier.name == o.requested):
        return None
    rejection = next((r for r in o.rejected if r.carrier_name == o.requested), None)
    fallback = "sıradaki uygun firma seçildi" if o.selected is not None else "başka uygun firma da yok"
    if rejection is None:  # cannot happen: a requested carrier is either first or rejected
        return None
    reasons = "; ".join(rejection.reasons)
    return f"Sipariş açıklamasında {o.requested} istendi ancak uygun değil ({reasons}); {fallback}."


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
        if o.selected.requested:
            return "Sipariş açıklamasında istenen firma; tüm kısıtları sağlayan tek firma."
        return "Tüm kısıtları sağlayan tek firma."
    runner_up = others[0]
    decided_by = deciding_criterion(o.selected, runner_up, rules)
    if decided_by is None:
        return f"{runner_up.carrier.name} ile tüm kriterler eşit."

    criterion = REQUESTED if decided_by == REQUESTED_KEY else CRITERIA[decided_by]
    comparison = (
        f"{criterion.label} — {o.selected.carrier.name}: {criterion.describe(o.selected)}, "
        f"{runner_up.carrier.name}: {criterion.describe(runner_up)}."
    )
    before = rules.ranking[: rules.ranking.index(decided_by)] if decided_by in rules.ranking else ()
    equal = [CRITERIA[name].label for name in before]
    if not equal:
        return f"Belirleyici kriter: {comparison}"
    tied = ", ".join(equal)
    return f"{tied[0].upper()}{tied[1:]} eşit; belirleyici kriter: {comparison}"
