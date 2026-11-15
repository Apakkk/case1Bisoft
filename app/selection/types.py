from dataclasses import dataclass
from decimal import Decimal

from app.models.carrier import Carrier


@dataclass(frozen=True, slots=True)
class Candidate:
    """A carrier that passed every hard constraint, with its price for this order."""

    carrier: Carrier
    total_cost: Decimal
    hq_distance: Decimal | None = None  # HQ -> order origin; None = unknown or not needed
    requested: bool = False  # the order description asks for this carrier (Jev)


@dataclass(frozen=True, slots=True)
class Rejection:
    carrier_name: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FilterResult:
    eligible: tuple[Candidate, ...]
    rejected: tuple[Rejection, ...]
