"""Quote flow: resolve order -> distance -> filter -> HQ distances -> rank -> compatibility -> status -> explanation.

Business rules live in app/selection (pure). Jev is consulted only where the *data* is free text:
the order's description (missing fields, requirements) and the carriers' descriptions. Low confidence
never becomes a guess: it becomes `needs_review` or `needs_input`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from app.clients.distance.chain import DistanceProvider, DistanceResult, UnknownLocationError
from app.clients.jev_client import (
    NO_REQUEST,
    ChoiceResult,
    CompatibilityCheck,
    JevClient,
    JevUnavailableError,
    RequestMeta,
)
from app.models.carrier import Carrier
from app.models.order import Order
from app.models.quote import JevCall, JevUsage, QuoteStatus, ResolvedOrder
from app.repositories.carrier_repository import CarrierRepository
from app.repositories.rules_repository import RulesSource
from app.schemas.quote import QuoteRequest
from app.selection.engine import (
    boundary_warnings,
    distance_sensitive,
    filter_carriers,
    needs_hq_distance,
    rank,
    with_hq_distances,
    with_requested,
)
from app.selection.explanation import Outcome, explain
from app.selection.order_text import parse_container_size
from app.selection.rules import RuleSet
from app.selection.types import Candidate, Rejection

HAZARDOUS = "Hazardous"
_FIELD_LABELS = {"container_size": "konteyner ölçüsü", "cargo_type": "yük tipi"}


class InvalidOrderError(ValueError):
    """The order contradicts the catalog or misses required data (HTTP 422)."""


@dataclass(frozen=True, slots=True)
class Quote:
    status: QuoteStatus
    order: ResolvedOrder
    selected: Candidate | None
    distance: DistanceResult | None
    ranking: tuple[Candidate, ...]
    rejected: tuple[Rejection, ...]
    jev_calls: tuple[JevCall, ...]
    warnings: tuple[str, ...]
    explanation: str
    requested: str | None = None  # carrier the order description asks for (Jev), if any
    hq_distances: Mapping[str, DistanceResult] = field(default_factory=dict)  # carrier -> HQ to origin
    jev_usage: JevUsage = field(default_factory=JevUsage)


@dataclass
class _Trace:
    """Per-request record of Jev answers, warnings and whether a human must review the result."""

    jev_calls: list[JevCall] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review: bool = False
    usage: JevUsage = field(default_factory=JevUsage)

    def flag(self, warning: str) -> None:
        self.warnings.append(warning)
        self.review = True

    def spent(self, meta: RequestMeta) -> None:
        """Count one answered Jev request (failed requests return no token count and are not counted)."""
        u = self.usage
        self.usage = JevUsage(
            u.requests + 1, u.input_tokens + (meta.input_tokens or 0), meta.model or u.model, u.cached + meta.cached
        )


class QuoteService:
    def __init__(
        self,
        carriers: CarrierRepository,
        distances: DistanceProvider,
        rules: RulesSource,
        jev: JevClient | None = None,
    ) -> None:
        self._carriers = carriers
        self._distances = distances
        self._rules = rules
        self._jev = jev

    def quote(self, request: QuoteRequest) -> Quote:
        rules = self._rules.get()
        trace = _Trace()
        if self._rules.problem:
            trace.warnings.append(self._rules.problem)
        order_note = (request.description or "").strip()
        resolved = self._resolve_order(request, rules, trace)
        if resolved.container_size is None or resolved.cargo_type is None:
            return self._needs_input(resolved, trace)

        order = Order(resolved.origin, resolved.destination, resolved.container_size, resolved.cargo_type)
        distance = self._distances.miles(
            order.origin, order.destination, approximate_factor=rules.distance.approximate_factor
        )
        trace.warnings.extend(distance.warnings)
        carriers = self._carriers.list()
        filtered = filter_carriers(carriers, order, distance.miles, rules)

        candidates = filtered.eligible
        hq_distances: dict[str, DistanceResult] = {}
        if len(candidates) > 1 and needs_hq_distance(rules):  # a single candidate needs no tie-break
            for c in candidates:
                hq_result = self._hq_distance(c.carrier, order.origin, rules, trace)
                if hq_result is not None:
                    hq_distances[c.carrier.name] = hq_result
            hq = {c.carrier.name: _miles_of(hq_distances.get(c.carrier.name)) for c in candidates}
            candidates = with_hq_distances(candidates, hq)
        notes = _notes_to_check(order_note, candidates, rules)
        check = self._ask_compatibility(order, order_note, notes, carriers, rules, trace)
        requested = self._requested(check, order_note, rules, trace)
        candidates = with_requested(candidates, requested)
        ranked, note_rejections = self._apply_compatibility(
            rank(candidates, rules), check, order_note, notes, rules, trace
        )

        if distance.approximate:
            near_limit = distance_sensitive(carriers, order, distance.miles, rules)
            for warning in boundary_warnings(near_limit, distance.miles, rules.distance.boundary_warning_ratio):
                trace.flag(warning)

        selected = ranked[0] if ranked else None
        if selected is None:
            status = QuoteStatus.NO_CARRIER
        else:
            status = QuoteStatus.NEEDS_REVIEW if trace.review else QuoteStatus.SELECTED

        rejected = (*filtered.rejected, *note_rejections)
        outcome = Outcome(order, distance.miles, distance.approximate, ranked, rejected, selected, requested)
        return Quote(
            status=status,
            order=resolved,
            selected=selected,
            distance=distance,
            ranking=ranked,
            rejected=rejected,
            jev_calls=tuple(trace.jev_calls),
            warnings=tuple(trace.warnings),
            explanation=explain(outcome, rules),
            requested=requested,
            hq_distances=hq_distances,
            jev_usage=trace.usage,
        )

    # --- order interpretation -------------------------------------------------------------

    def _resolve_order(self, request: QuoteRequest, rules: RuleSet, trace: _Trace) -> ResolvedOrder:
        text = (request.description or "").strip()
        if (request.container_size is None or request.cargo_type is None) and not text:
            raise InvalidOrderError("send container_size and cargo_type, or describe the cargo in description")
        # Cities first: an unknown one fails here (with suggestions), before any Jev tokens are spent.
        origin = self._distances.normalize(request.origin)
        destination = self._distances.normalize(request.destination)

        inferred: dict[str, str] = {}
        size = request.container_size
        if size is not None and size not in rules.container_sizes:
            allowed = ", ".join(map(str, rules.container_sizes))
            raise InvalidOrderError(f"container_size {size} is not in the catalog ({allowed})")
        if size is None:
            size = parse_container_size(text, rules.container_sizes)  # deterministic first
            if size is not None:
                inferred["container_size"] = "text"

        cargo: str | None = None
        if request.cargo_type is not None:
            cargo = rules.canonical_cargo_type(request.cargo_type)
            if cargo is None:
                raise InvalidOrderError(
                    f"cargo_type '{request.cargo_type}' is not in the catalog ({', '.join(rules.cargo_types)})"
                )

        if size is None or cargo is None:
            jev_size, jev_cargo = self._interpret(
                text, rules, need_size=size is None, need_cargo=cargo is None, trace=trace
            )
            if size is None and jev_size is not None:
                size, inferred["container_size"] = jev_size, "jev"
            if cargo is None and jev_cargo is not None:
                cargo, inferred["cargo_type"] = jev_cargo, "jev"

        return ResolvedOrder(
            origin=origin,
            destination=destination,
            origin_state=self._distances.state_of(origin),
            destination_state=self._distances.state_of(destination),
            container_size=size,
            cargo_type=cargo,
            inferred=inferred,
        )

    def _interpret(
        self, text: str, rules: RuleSet, *, need_size: bool, need_cargo: bool, trace: _Trace
    ) -> tuple[int | None, str | None]:
        if self._jev is None:
            trace.warnings.append("Jev yapılandırılmamış; serbest metin yorumlanamadı.")
            return None, None
        try:
            result = self._jev.classify_order(
                text,
                rules.cargo_types if need_cargo else None,
                rules.container_sizes if need_size else None,
            )
        except JevUnavailableError:
            trace.warnings.append("Jev'e ulaşılamadı; serbest metin yorumlanamadı.")
            return None, None
        trace.spent(result.meta)

        cargo = self._accept("cargo_type", result.cargo_type, result.elapsed_ms, text, rules, trace)
        size_label = self._accept("container_size", result.container_size, result.elapsed_ms, text, rules, trace)

        if result.cargo_type is not None and cargo is not None and cargo != HAZARDOUS:
            p_hazardous = result.cargo_type.probabilities.get(HAZARDOUS, 0.0)
            if p_hazardous >= rules.confidence.hazardous_review:
                trace.flag(
                    f"Tehlikeli yük olasılığı {p_hazardous:.2f} (eşik {rules.confidence.hazardous_review:.2f}); "
                    "manuel inceleme gerekli."
                )
        return (int(size_label) if size_label is not None else None), cargo

    def _accept(
        self, name: str, choice: ChoiceResult | None, elapsed_ms: int, text: str, rules: RuleSet, trace: _Trace
    ) -> str | None:
        """Apply the confidence bands: accept, accept-with-review, or refuse to guess."""
        if choice is None:
            return None
        trace.jev_calls.append(JevCall(name, _short(text), choice.choice, round(choice.confidence, 3), elapsed_ms))
        label, bands = _FIELD_LABELS[name], rules.confidence
        if choice.confidence >= bands.auto_accept:
            return choice.choice
        if choice.confidence >= bands.needs_review:
            trace.flag(
                f"{label.capitalize()} Jev ile düşük güvenle belirlendi ({choice.choice}, güven "
                f"{choice.confidence:.2f}); manuel onay gerekli."
            )
            return choice.choice
        trace.warnings.append(
            f"{label.capitalize()} için Jev güveni çok düşük ({choice.choice}?, güven {choice.confidence:.2f}); "
            "tahmin edilmedi."
        )
        return None

    def _needs_input(self, order: ResolvedOrder, trace: _Trace) -> Quote:
        missing = [label for name, label in _FIELD_LABELS.items() if getattr(order, name) is None]
        return Quote(
            status=QuoteStatus.NEEDS_INPUT,
            order=order,
            selected=None,
            distance=None,
            ranking=(),
            rejected=(),
            jev_calls=tuple(trace.jev_calls),
            warnings=tuple(trace.warnings),
            explanation=f"Firma seçilmedi: {' ve '.join(missing)} belirlenemedi. Lütfen açıkça belirtin.",
            jev_usage=trace.usage,
        )

    # --- order note <-> carrier descriptions -------------------------------------------------

    def _ask_compatibility(
        self,
        order: Order,
        order_note: str,
        notes: dict[str, str],
        carriers: list[Carrier],
        rules: RuleSet,
        trace: _Trace,
    ) -> CompatibilityCheck | None:
        """One Jev request: conflicts for the eligible carriers and, with an order note, the requested carrier."""
        if not notes:
            return None
        what = "sipariş açıklaması ve firma notları" if order_note else "firma notları"
        if self._jev is None:
            trace.flag(f"{what.capitalize()} kontrol edilemedi (Jev yapılandırılmamış): {', '.join(notes)}.")
            return None
        # Every carrier name, not only eligible ones: a requested but ineligible carrier is named with its reasons.
        requestable = [c.name for c in carriers] if order_note else []
        try:
            check = self._jev.check_compatibility(order, order_note, notes, requestable)
        except JevUnavailableError:
            trace.flag(f"Jev'e ulaşılamadı; {what} kontrol edilmedi: {', '.join(notes)}.")
            return None
        trace.spent(check.meta)
        return check

    def _requested(
        self, check: CompatibilityCheck | None, order_note: str, rules: RuleSet, trace: _Trace
    ) -> str | None:
        """The carrier the order note asks for, through the same confidence bands as every Jev answer."""
        if check is None or check.requested is None:
            return None
        choice, bands = check.requested, rules.confidence
        trace.jev_calls.append(
            JevCall(
                "requested_carrier", _short(order_note), choice.choice, round(choice.confidence, 3), check.elapsed_ms
            )
        )
        if choice.choice == NO_REQUEST:
            return None
        if choice.confidence >= bands.auto_accept:
            return choice.choice
        if choice.confidence >= bands.needs_review:
            trace.flag(
                f"İstenen firma Jev ile düşük güvenle belirlendi ({choice.choice}, güven {choice.confidence:.2f}); "
                "manuel onay gerekli."
            )
            return choice.choice
        trace.warnings.append(
            f"Sipariş açıklamasında istenen firma belirlenemedi ({choice.choice}?, güven {choice.confidence:.2f}); "
            "öncelik sırası uygulandı."
        )
        return None

    def _apply_compatibility(
        self,
        ranked: tuple[Candidate, ...],
        check: CompatibilityCheck | None,
        order_note: str,
        notes: dict[str, str],
        rules: RuleSet,
        trace: _Trace,
    ) -> tuple[tuple[Candidate, ...], tuple[Rejection, ...]]:
        """Free text only narrows: a confident conflict removes a carrier; an unsure one on the winner needs review."""
        if check is None:
            return ranked, ()
        block_at = rules.confidence.auto_accept
        allow_at = 1 - block_at
        remaining: list[Candidate] = []
        rejections: list[Rejection] = []
        uncertain: dict[str, float] = {}
        for candidate in ranked:
            name = candidate.carrier.name
            p = check.conflict_probability.get(name)
            if p is None:
                remaining.append(candidate)
                continue
            answer = "conflict" if p >= 0.5 else "compatible"
            trace.jev_calls.append(JevCall("compatibility", name, answer, round(p, 3), check.elapsed_ms))
            if p >= block_at:
                rejections.append(Rejection(name, (_conflict_reason(order_note, notes[name], p),)))
                continue
            if p > allow_at:
                uncertain[name] = p
            remaining.append(candidate)

        if remaining and remaining[0].carrier.name in uncertain:
            top, p = remaining[0].carrier.name, uncertain[remaining[0].carrier.name]
            if order_note:
                message = f"{top} ile sipariş açıklamasının uyumu belirsiz (uyumsuzluk olasılığı {p:.2f})"
            else:
                message = f"{top} notunun bu siparişe etkisi belirsiz (engelleme olasılığı {p:.2f})"
            trace.flag(f"{message}; manuel onay gerekli.")
        return tuple(remaining), tuple(rejections)

    def _hq_distance(self, carrier: Carrier, origin: str, rules: RuleSet, trace: _Trace) -> DistanceResult | None:
        factor = rules.distance.approximate_factor
        try:
            result = self._distances.miles(carrier.hq_city, origin, approximate_factor=factor)
        except UnknownLocationError:
            trace.warnings.append(
                f"{carrier.name} merkezi ({carrier.hq_city}) bulunamadı; yakınlık kriterinde sona alındı."
            )
            return None
        if result.approximate:
            trace.warnings.append(
                f"{carrier.name} merkezi ({carrier.hq_city}) → {origin} mesafesi yaklaşık: kuş uçuşu × {factor}."
            )
        trace.warnings.extend(w for w in result.warnings if w not in trace.warnings)
        return result


def _miles_of(result: DistanceResult | None) -> Decimal | None:
    return result.miles if result is not None else None


def _notes_to_check(order_note: str, candidates: tuple[Candidate, ...], rules: RuleSet) -> dict[str, str]:
    """With an order note every eligible carrier is compared (the note may name any of them); without one,
    only descriptions that may restrict orders under today's threshold. Ineligible carriers are never compared:
    they are already out."""
    if order_note:
        return {c.carrier.name: c.carrier.description for c in candidates}
    auto_accept = rules.confidence.auto_accept
    return {c.carrier.name: c.carrier.description for c in candidates if c.carrier.note_may_restrict(auto_accept)}


def _conflict_reason(order_note: str, description: str, p: float) -> str:
    """Quote the texts Jev compared, so the operator sees why the carrier was removed."""
    if not order_note:
        return f'Firma notu bu siparişi engelliyor: "{_short(description)}" (Jev, olasılık {p:.2f})'
    if not description:
        return f'Sipariş açıklamasıyla uyumsuz: "{_short(order_note)}" (Jev, olasılık {p:.2f})'
    return f'Açıklamalar uyumsuz: sipariş "{_short(order_note)}", firma "{_short(description)}" (Jev, olasılık {p:.2f})'


def _short(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
