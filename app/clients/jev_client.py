"""Jev (TypeSafe System One) behind a domain-level interface.

Jev only answers semantic questions: which catalog value a free-text order means, and whether a
carrier's free-text note rules an order out. Prices, distances, ranking and explanations never go
through it. Questions are batched into one request because every request has a fixed token cost.
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
class NotesCheck:
    block_probability: Mapping[str, float]  # carrier name -> P(note rules the order out)
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class NotePrecheck:
    restriction_probability: float  # P(the note restricts which orders the carrier accepts)
    elapsed_ms: int


class JevClient(Protocol):
    def classify_order(
        self, text: str, cargo_types: Sequence[str] | None, container_sizes: Sequence[int] | None
    ) -> OrderClassification: ...

    def notes_block_order(self, order: Order, notes: Mapping[str, str]) -> NotesCheck: ...

    def note_has_restriction(self, note: str) -> NotePrecheck: ...


# Short label descriptions: input tokens are what Jev bills.
CARGO_DESCRIPTIONS = {
    "Dry": "general cargo; no temperature control; not dangerous",
    "Reefer": "perishable; must be refrigerated or frozen",
    "Hazardous": "dangerous goods: flammable, explosive, toxic, corrosive, gases, lithium batteries",
}
NOTE_BLOCKS: NoulCriteria = {
    "true": "The note states a restriction that this order violates.",
    "false": "The note has no restriction, or none of its restrictions apply to this order.",
}
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

    def notes_block_order(self, order: Order, notes: Mapping[str, str]) -> NotesCheck:
        names = list(notes)
        state = {
            "order": {
                "origin": order.origin,
                "destination": order.destination,
                "container_size_ft": order.container_size,
                "cargo_type": order.cargo_type,
            },
            "carrier_notes": dict(notes),
        }
        questions = {
            f"c{i}": Noul(instructions=f"Does carrier_notes['{name}'] rule out this order?", criteria=NOTE_BLOCKS)
            for i, name in enumerate(names)
        }
        result, elapsed = self._ask(state, questions)
        return NotesCheck({name: result.nouls[f"c{i}"].noul for i, name in enumerate(names)}, elapsed)

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
