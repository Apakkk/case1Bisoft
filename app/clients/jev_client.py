"""Jev (TypeSafe System One) behind a domain-level interface.

Jev only answers semantic questions: which catalog value a free-text order means, and whether an
order's free text and a carrier's free-text description are compatible. Prices, distances, ranking and
explanations never go through it. Questions are batched into one request because every request has a fixed token cost.
"""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from typesafe_sdk import Choice, Noul, NoulCriteria, RetryPolicy, SystemOneResponse, TypeSafeClient, TypeSafeError

from app.clients.jev_cache import JevAnswerCache, question_key
from app.models.order import Order

logger = logging.getLogger(__name__)

# After a failure Jev is not asked for this long: during an outage every request would otherwise wait for the
# timeout and one retry (~10 s with the settings below) before degrading to review.
OUTAGE_PAUSE_SECONDS = 30.0


class JevUnavailableError(Exception):
    """Jev could not answer (network, timeout, auth, quota). Callers degrade to human review."""


@dataclass(frozen=True, slots=True)
class RequestMeta:
    """What one Jev request cost and which model answered it (None when the API did not say)."""

    input_tokens: int | None = None  # billable; 0 for an answer from the cache
    model: str | None = None
    cached: bool = False  # answered from memory, no request sent
    requested_model: str | None = None  # JEV_MODEL as configured (None: the SDK default)

    @property
    def unexpected_model(self) -> bool:
        """A pinned version was asked for but another one answered (an alias such as jev-latest pins nothing)."""
        pinned = self.requested_model is not None and not self.requested_model.endswith(("-latest", "-preview"))
        return pinned and self.model is not None and self.model != self.requested_model


@dataclass(frozen=True, slots=True)
class ChoiceResult:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class OrderClassification:
    cargo_type: ChoiceResult | None
    container_size: ChoiceResult | None
    elapsed_ms: int
    meta: RequestMeta = field(default_factory=RequestMeta)


@dataclass(frozen=True, slots=True)
class CompatibilityCheck:
    conflict_probability: Mapping[str, float]  # carrier name -> P(the order and the carrier do not fit)
    elapsed_ms: int
    requested: ChoiceResult | None = None  # which carrier the order note asks for (NO_REQUEST = none)
    meta: RequestMeta = field(default_factory=RequestMeta)


@dataclass(frozen=True, slots=True)
class NotePrecheck:
    restriction_probability: float  # P(the note restricts which orders the carrier accepts)
    elapsed_ms: int
    meta: RequestMeta = field(default_factory=RequestMeta)


class JevClient(Protocol):
    def classify_order(
        self, text: str, cargo_types: Sequence[str] | None, container_sizes: Sequence[int] | None
    ) -> OrderClassification: ...

    def check_compatibility(
        self, order: Order, order_note: str, carrier_notes: Mapping[str, str], requestable: Sequence[str] = ()
    ) -> CompatibilityCheck: ...

    def note_has_restriction(self, note: str) -> NotePrecheck: ...


# Short label descriptions: input tokens are what Jev bills.
CARGO_DESCRIPTIONS = {
    "Dry": "general cargo; no temperature control; not dangerous",
    "Reefer": "perishable; must be refrigerated or frozen",
    "Hazardous": "dangerous goods: flammable, explosive, toxic, corrosive, gases, lithium batteries",
}
# Offered with every cargo question: without it a text about carriers or dates would be forced into a cargo type.
NOT_STATED = "not_stated"
NOT_STATED_DESCRIPTION = "the text does not say what the cargo is"
CONFLICT: NoulCriteria = {
    "true": "Clear conflict for this carrier: the order note refuses it or demands something its description "
    "contradicts, or its description excludes this order.",
    "false": "No clear conflict for this carrier. Asking for another carrier, a note about other carriers, "
    "or missing information is not a conflict.",
}
NO_REQUEST = "no_specific_carrier"
REQUESTED = "Which carrier does the order note explicitly ask to use? Refusing a carrier is not asking for one."
NOTE_RESTRICTS = "Does this carrier description restrict which orders the carrier accepts?"
# Both outcomes described, like CONFLICT: without the "false" side, capability claims that mention cargo ("all cargo
# types", "her şey taşınır") landed in the grey zone (0.17-0.24) and showed as restrictions.
NOTE_RESTRICTION: NoulCriteria = {
    "true": "It refuses or limits orders: a cargo type, container size, route or region, distance, or days "
    "it does not take, or says it only takes certain ones.",
    "false": "It only describes capabilities, coverage or experience and excludes nothing "
    "(e.g. 'nationwide', 'all cargo types', 'we carry everything').",
}


class SystemOne(Protocol):
    """The one SDK call this client makes (TypeSafeClient; a scripted stand-in in tests)."""

    def system_one(self, state: Any, questions: Mapping[str, Any]) -> SystemOneResponse: ...


class TypesafeJevClient:
    def __init__(
        self,
        api_key: str,
        model: str | None,
        timeout: float,
        *,
        client: SystemOne | None = None,
        clock: Callable[[], float] = time.monotonic,
        cache: JevAnswerCache | None = None,
    ) -> None:
        self._client: SystemOne = client or TypeSafeClient(
            api_key=api_key, model=model, timeout=timeout, retry=RetryPolicy(max_retries=1)
        )
        self._model = model
        self._clock = clock
        self._cache = cache
        self._paused_until = 0.0  # set after a failure; until then requests fail at once

    def classify_order(
        self, text: str, cargo_types: Sequence[str] | None, container_sizes: Sequence[int] | None
    ) -> OrderClassification:
        questions: dict[str, Any] = {}
        if cargo_types:
            criteria: dict[str, str | None] = {t: CARGO_DESCRIPTIONS.get(t) for t in cargo_types}
            criteria[NOT_STATED] = NOT_STATED_DESCRIPTION
            questions["cargo_type"] = Choice(instructions="Cargo category of this shipment", criteria=criteria)
        if container_sizes:
            questions["container_size"] = Choice(
                instructions="Container length in feet stated in the text",
                criteria={str(s): None for s in container_sizes},
            )
        result, elapsed, meta = self._ask("classify_order", text, questions)
        return OrderClassification(
            cargo_type=_choice(result, "cargo_type"),
            container_size=_choice(result, "container_size"),
            elapsed_ms=elapsed,
            meta=meta,
        )

    def check_compatibility(
        self, order: Order, order_note: str, carrier_notes: Mapping[str, str], requestable: Sequence[str] = ()
    ) -> CompatibilityCheck:
        """One request for all candidates: does the order (and its note) fit each carrier's description?

        With `requestable` (every carrier name, eligible or not) the same request also asks which carrier
        the note asks for, so an ineligible requested carrier can still be named with its reasons.
        """
        names = list(carrier_notes)
        order_state: dict[str, Any] = {
            "origin": order.origin,
            "destination": order.destination,
            "container_size_ft": order.container_size,
            "cargo_type": order.cargo_type,
        }
        if order_note:
            order_state["note"] = order_note
        state = {"order": order_state, "carrier_descriptions": {name: carrier_notes[name] for name in names}}
        questions: dict[str, Any] = {
            f"c{i}": Noul(
                instructions=f"Is carrier '{name}' ruled out for this order by the order note "
                "or by its own description?",
                criteria=CONFLICT,
            )
            for i, name in enumerate(names)
        }
        if order_note and requestable:
            labels: dict[str, str | None] = {name: None for name in requestable}
            labels[NO_REQUEST] = "The note asks for no specific carrier"
            questions["requested"] = Choice(instructions=REQUESTED, criteria=labels)
        result, elapsed, meta = self._ask("check_compatibility", state, questions)
        conflicts = {name: result.nouls[f"c{i}"].noul for i, name in enumerate(names)}
        return CompatibilityCheck(conflicts, elapsed, _choice(result, "requested"), meta)

    def note_has_restriction(self, note: str) -> NotePrecheck:
        result, elapsed, meta = self._ask(
            "note_has_restriction", note, {"restricts": Noul(instructions=NOTE_RESTRICTS, criteria=NOTE_RESTRICTION)}
        )
        return NotePrecheck(result.nouls["restricts"].noul, elapsed, meta)

    def _ask(self, what: str, state: Any, questions: Mapping[str, Any]) -> tuple[SystemOneResponse, int, RequestMeta]:
        """The single way to Jev: memory first (even while paused), then the pause, then one request."""
        key = question_key(self._model, state, questions) if self._cache is not None else None
        if self._cache is not None and key is not None:
            remembered = self._cache.get(key)
            if remembered is not None:
                logger.info("jev %s: answered from the cache, model %s", what, remembered.model)
                return remembered, 0, RequestMeta(0, remembered.model, cached=True, requested_model=self._model)
        wait = self._paused_until - self._clock()
        if wait > 0:
            raise JevUnavailableError(f"not asked for another {wait:.0f} s after a recent failure")
        started = time.perf_counter()
        try:
            result = self._client.system_one(state=state, questions=questions)
        except TypeSafeError as error:
            self._paused_until = self._clock() + OUTAGE_PAUSE_SECONDS
            logger.warning("jev %s failed (%s); not asked again for %.0f s", what, error, OUTAGE_PAUSE_SECONDS)
            raise JevUnavailableError(str(error)) from error
        elapsed = int((time.perf_counter() - started) * 1000)
        if self._cache is not None and key is not None:
            self._cache.put(key, result)
        meta = RequestMeta(result.usage.input_tokens, result.model, requested_model=self._model)
        logger.info("jev %s: %s input tokens, model %s, %d ms", what, meta.input_tokens, meta.model, elapsed)
        return result, elapsed, meta


def _choice(result: SystemOneResponse, name: str) -> ChoiceResult | None:
    answer = result.choices.get(name)
    if answer is None:
        return None
    return ChoiceResult(answer.choice, answer.confidence, dict(answer.probabilities))
