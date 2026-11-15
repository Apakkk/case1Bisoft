from dataclasses import dataclass, field
from enum import StrEnum


class QuoteStatus(StrEnum):
    SELECTED = "selected"  # carrier chosen, nothing uncertain
    NEEDS_REVIEW = "needs_review"  # carrier chosen, but something uncertain needs a human look
    NEEDS_INPUT = "needs_input"  # order too ambiguous to decide; no carrier chosen
    NO_CARRIER = "no_carrier"  # every carrier fails a constraint (reasons included)
    NEEDS_CONFIRMATION = "needs_confirmation"  # the description contradicts an entered field; resend confirmed


@dataclass(frozen=True, slots=True)
class JevCall:
    """One answer from Jev, kept in the response so every model influence is visible."""

    step: str  # cargo_type | container_size | cargo_check | requested_carrier | compatibility
    subject: str  # what was asked about (e.g. carrier name)
    answer: str  # chosen label or "yes"/"no"
    confidence: float  # choice confidence, or P(yes) for yes/no questions
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class JevUsage:
    """What a quote cost at Jev: questions answered (some from memory), billable input tokens, the model."""

    requests: int = 0
    input_tokens: int = 0
    model: str | None = None
    cached: int = 0  # of `requests`, answered from memory at no cost


@dataclass(frozen=True, slots=True)
class ResolvedOrder:
    """The order after normalization; fields may still be None when they could not be resolved."""

    origin: str
    destination: str
    container_size: int | None
    cargo_type: str | None
    inferred: dict[str, str] = field(default_factory=dict)  # field -> "text" (regex) | "jev"
    origin_state: str = ""  # two-letter US state, shown next to the city ('Paris' -> 'Paris, TX')
    destination_state: str = ""
