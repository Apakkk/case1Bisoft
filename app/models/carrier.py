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

    def note_may_restrict(self, auto_accept: float) -> bool:
        """Whether the description may restrict orders, judged against today's threshold (rules.yaml).

        The probability Jev gave when the note was saved is compared with the current cut-off, so a changed
        threshold applies to old notes too. The stored status decides only when there is no probability: seeded as
        harmless, or never checked because Jev was unavailable.
        """
        if not self.description:
            return False
        if self.note_confidence is None:
            return self.note_status is not NoteStatus.NONE
        return self.note_confidence > 1 - auto_accept

    def note_uncertain(self, auto_accept: float) -> bool:
        """Jev was not sure either way (between the two cut-offs): shown as "Belirsiz", not as a restriction.

        Such a note is still sent with every order (`note_may_restrict`); only the label differs from a note
        Jev judged restrictive with confidence (P >= auto_accept).
        """
        return (
            self.note_may_restrict(auto_accept)
            and self.note_confidence is not None
            and self.note_confidence < auto_accept
        )
