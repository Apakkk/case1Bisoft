"""Does the order's description contradict a field the user entered? Pure: the caller supplies what the text says.

A field typed by the user is never overridden. When the description says something else, the quote stops and asks
the user to confirm (status `needs_confirmation`); a confirmed order goes on with the entered value and the
mismatch stays in the warnings.
"""

from dataclasses import dataclass
from typing import Literal

from app.selection.rules import ConfidenceThresholds

OrderField = Literal["cargo_type", "container_size"]

FIELD_LABELS: dict[OrderField, str] = {"cargo_type": "yük tipi", "container_size": "konteyner ölçüsü"}


@dataclass(frozen=True, slots=True)
class Mismatch:
    field: OrderField
    entered: str
    described: str  # what the description says instead
    confidence: float | None  # Jev's confidence; None when the text was parsed deterministically
    source: Literal["jev", "text"]

    def detail(self) -> str:
        """'girilen Dry, açıklamaya göre Hazardous (Jev, güven 0.93)'"""
        how = f"Jev, güven {self.confidence:.2f}" if self.confidence is not None else "açıklamadaki ölçü"
        return f"girilen {self.entered}, açıklamaya göre {self.described} ({how})"


def cargo_mismatch(
    entered: str, described: str | None, confidence: float, bands: ConfidenceThresholds
) -> Mismatch | None:
    """Jev read another cargo type in the description, sure enough that it would have filled an empty field with it.

    `described` is None when Jev found no cargo in the text (a note about carriers, dates, ...): nothing to contradict.
    """
    if described is None or described == entered or confidence < bands.needs_review:
        return None
    return Mismatch("cargo_type", entered, described, confidence, "jev")


def size_mismatch(entered: int, parsed: int | None) -> Mismatch | None:
    """The description states another container size ('40'lık') than the one entered."""
    if parsed is None or parsed == entered:
        return None
    return Mismatch("container_size", f"{entered} ft", f"{parsed} ft", None, "text")


def confirmation_question(mismatches: tuple[Mismatch, ...]) -> str:
    """'Girilen yük tipi ile açıklama uyumsuz. Bu şekilde devam etmek istiyor musunuz?'"""
    fields = " ve ".join(FIELD_LABELS[m.field] for m in mismatches)
    return f"Girilen {fields} ile açıklama uyumsuz. Bu şekilde devam etmek istiyor musunuz?"
