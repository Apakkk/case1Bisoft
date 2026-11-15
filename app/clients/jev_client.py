"""Jev (TypeSafe System One) behind a domain-level interface.

Jev only answers semantic questions: which catalog value a free-text order means, and whether an
order's free text and a carrier's free-text description are compatible. Prices, distances, ranking and
explanations never go through it. Questions are batched into one request because every request has a fixed token cost.
"""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from typesafe_sdk import Choice, Noul, NoulCriteria, RetryPolicy, SystemOneResponse, TypeSafeClient, TypeSafeError

from app.models.order import Order


class JevUnavailableError(Exception):
    """Jev could not answer (network, timeout, auth, quota). Callers degrade to human review."""


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


@dataclass(frozen=True, slots=True)
class CompatibilityCheck:
    conflict_probability: Mapping[str, float]  # carrier name -> P(the order and the carrier do not fit)
    elapsed_ms: int
    requested: ChoiceResult | None = None  # which carrier the order note asks for (NO_REQUEST = none)


@dataclass(frozen=True, slots=True)
class NotePrecheck:
    restriction_probability: float  # P(the note restricts which orders the carrier accepts)
    elapsed_ms: int


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
CONFLICT: NoulCriteria = {
    "true": "Clear conflict for this carrier: the order note refuses it or demands something its description "
    "contradicts, or its description excludes this order.",
    "false": "No clear conflict for this carrier. Asking for another carrier, a note about other carriers, "
    "or missing information is not a conflict.",
}
NO_REQUEST = "no_specific_carrier"
REQUESTED = "Which carrier does the order note explicitly ask to use? Refusing a carrier is not asking for one."
NOTE_RESTRICTS = (
    "Does this carrier description restrict which orders the carrier accepts "
    "(cargo, container sizes, routes, distances, dates)?"
)


class TypesafeJevClient:
    def __init__(self, api_key: str, model: str | None, timeout: float) -> None:
        self._client = TypeSafeClient(api_key=api_key, model=model, timeout=timeout, retry=RetryPolicy(max_retries=1))

    def classify_order(
        self, text: str, cargo_types: Sequence[str] | None, container_sizes: Sequence[int] | None
    ) -> OrderClassification:
        questions: dict[str, Any] = {}
        if cargo_types:
            questions["cargo_type"] = Choice(
                instructions="Cargo category of this shipment",
                criteria={t: CARGO_DESCRIPTIONS.get(t) for t in cargo_types},
            )
        if container_sizes:
            questions["container_size"] = Choice(
                instructions="Container length in feet stated in the text",
                criteria={str(s): None for s in container_sizes},
            )
        result, elapsed = self._ask(text, questions)
        return OrderClassification(
            cargo_type=_choice(result, "cargo_type"),
            container_size=_choice(result, "container_size"),
            elapsed_ms=elapsed,
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
        result, elapsed = self._ask(state, questions)
        conflicts = {name: result.nouls[f"c{i}"].noul for i, name in enumerate(names)}
        return CompatibilityCheck(conflicts, elapsed, _choice(result, "requested"))

    def note_has_restriction(self, note: str) -> NotePrecheck:
        result, elapsed = self._ask(note, {"restricts": Noul(instructions=NOTE_RESTRICTS)})
        return NotePrecheck(result.nouls["restricts"].noul, elapsed)

    def _ask(self, state: Any, questions: Mapping[str, Any]) -> tuple[SystemOneResponse, int]:
        started = time.perf_counter()
        try:
            result = self._client.system_one(state=state, questions=questions)
        except TypeSafeError as error:
            raise JevUnavailableError(str(error)) from error
        return result, int((time.perf_counter() - started) * 1000)


def _choice(result: SystemOneResponse, name: str) -> ChoiceResult | None:
    answer = result.choices.get(name)
    if answer is None:
        return None
    return ChoiceResult(answer.choice, answer.confidence, dict(answer.probabilities))
