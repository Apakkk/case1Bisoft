"""Form view-models: raw HTML form strings in, CarrierIn/QuoteRequest out, Turkish field errors back."""

import re
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Form
from pydantic import ValidationError

from app.models.carrier import Carrier
from app.schemas.carrier import CarrierIn
from app.selection.catalog import MAX_CONTAINER_FT
from app.selection.formatting import fmt_miles

_MESSAGES = {
    "missing": "Zorunlu alan.",
    "string_too_short": "Zorunlu alan.",
    "too_short": "En az bir seçim yapın.",
    "decimal_parsing": "Geçerli bir sayı girin.",
    "decimal_type": "Geçerli bir sayı girin.",
    "int_parsing": "Geçerli bir sayı girin.",
    "greater_than": "0'dan büyük olmalı.",
    "greater_than_equal": "Negatif olamaz.",
    "less_than_equal": f"En fazla {MAX_CONTAINER_FT} olabilir.",
    "decimal_max_places": "Çok fazla ondalık basamak.",
    "decimal_max_digits": "Sayı çok büyük.",
}
_VALUE_ERRORS = {
    "must not be blank": "Zorunlu alan.",
    "min_miles must be less than or equal to max_miles": "Min mesafe, max mesafeden büyük olamaz.",
}


def form_errors(error: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for item in error.errors(include_url=False):
        name = str(item["loc"][0]) if item["loc"] else "max_miles"  # model-level check = the range
        if item["type"] != "too_short" and item.get("input") in (None, ""):
            errors.setdefault(name, "Zorunlu alan.")
            continue
        message = str(item["msg"]).removeprefix("Value error, ")
        errors.setdefault(name, _VALUE_ERRORS.get(message) or _MESSAGES.get(item["type"], message))
    return errors


@dataclass
class CarrierForm:
    name: str = ""
    hq_city: str = ""
    rate_per_mile: str = ""
    min_miles: str = ""
    max_miles: str = ""
    container_sizes: list[str] = field(default_factory=list)  # ticked boxes
    other_sizes: str = ""  # typed sizes outside the boxes: "48, 53"
    cargo_types: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_carrier(cls, carrier: Carrier) -> "CarrierForm":
        return cls(
            name=carrier.name,
            hq_city=carrier.hq_city,
            rate_per_mile=f"{carrier.rate_per_mile.normalize():f}",
            min_miles=fmt_miles(carrier.min_miles) if carrier.min_miles is not None else "",
            max_miles=fmt_miles(carrier.max_miles) if carrier.max_miles is not None else "",
            container_sizes=[str(s) for s in sorted(carrier.container_sizes)],
            cargo_types=sorted(carrier.cargo_types),
            description=carrier.description,
        )

    def to_input(self) -> CarrierIn:
        """Raises ValidationError; blank optional numbers mean "no limit"."""
        return CarrierIn.model_validate(
            {
                "name": self.name,
                "hq_city": self.hq_city,
                "rate_per_mile": self.rate_per_mile.strip() or None,
                "min_miles": self.min_miles.strip() or None,
                "max_miles": self.max_miles.strip() or None,
                "container_sizes": [*self.container_sizes, *_typed_sizes(self.other_sizes)],
                "cargo_types": self.cargo_types,
                "description": self.description,
            }
        )


def read_carrier_form(
    name: Annotated[str, Form()] = "",
    hq_city: Annotated[str, Form()] = "",
    rate_per_mile: Annotated[str, Form()] = "",
    min_miles: Annotated[str, Form()] = "",
    max_miles: Annotated[str, Form()] = "",
    container_sizes: Annotated[list[str] | None, Form()] = None,
    other_sizes: Annotated[str, Form()] = "",
    cargo_types: Annotated[list[str] | None, Form()] = None,
    description: Annotated[str, Form()] = "",
) -> CarrierForm:
    return CarrierForm(
        name=name,
        hq_city=hq_city,
        rate_per_mile=rate_per_mile,
        min_miles=min_miles,
        max_miles=max_miles,
        container_sizes=container_sizes or [],
        other_sizes=other_sizes,
        cargo_types=cargo_types or [],
        description=description,
    )


def _typed_sizes(text: str) -> list[str]:
    """Typed sizes: "48, 53 ft" -> ["48", "53"]. Anything else is passed on as typed, so validation reports it."""
    without_units = re.sub(r"\s*(?:feet|ft|')", "", text, flags=re.IGNORECASE)
    return [token for token in re.split(r"[,;\s]+", without_units) if token]
