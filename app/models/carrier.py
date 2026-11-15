from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class NoteStatus(StrEnum):
    """Result of Jev's pre-check of a carrier's free-text description, stored when it is saved."""

    NONE = "none"  # no restriction in the note: no Jev call needed at quote time
    CONSTRAINT = "constraint"  # may restrict orders: checked against each order by Jev
    UNCHECKED = "unchecked"  # Jev was unavailable at save time: treated like CONSTRAINT


@dataclass(frozen=True, slots=True)
class Carrier:
    name: str
    hq_city: str
    min_miles: Decimal | None  # None = no lower bound
    max_miles: Decimal | None  # None = no upper bound
    container_sizes: frozenset[int]
    cargo_types: frozenset[str]
    rate_per_mile: Decimal
    description: str = ""
    note_status: NoteStatus = NoteStatus.NONE
    note_confidence: float | None = None
    id: int | None = None
