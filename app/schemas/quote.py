"""API DTOs for quotes. Money and miles are Decimals, serialized as strings (no float rounding)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.quote import QuoteStatus

if TYPE_CHECKING:
    from app.clients.distance.chain import DistanceResult
    from app.services.quote_service import Quote


class QuoteRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",  # an unknown field (e.g. a misspelled "description") is a 422, never silently ignored
        json_schema_extra={
            "examples": [
                {"origin": "Miami", "destination": "Atlanta", "container_size": 20, "cargo_type": "Reefer"},
                {"origin": "Miami", "destination": "Atlanta", "description": "20'lik konteynerde donmuş karides"},
                {
                    "origin": "Miami",
                    "destination": "Orlando",
                    "container_size": 40,
                    "cargo_type": "Dry",
                    "description": "S-Logistics ile çalışmak istemiyorum",
                },
            ]
        },
    )

    origin: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    container_size: int | None = Field(default=None, gt=0, description="Feet; must be in the catalog")
    cargo_type: str | None = Field(default=None, max_length=50, description="Catalog value, case-insensitive")
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Free text: fills fields not sent explicitly, and is matched against every eligible "
        "carrier's description by Jev (a conflict removes the carrier)",
    )


class DistanceOut(BaseModel):
    miles: Decimal
    source: str = Field(description="same_city | case_table | cache (earlier ORS answer) | ors | haversine")
    approximate: bool


class OrderOut(BaseModel):
    origin: str
    destination: str
    origin_state: str = Field(description="US state code of the resolved origin ('' if unknown)")
    destination_state: str = Field(description="US state code of the resolved destination ('' if unknown)")
    container_size: int | None
    cargo_type: str | None
    inferred: dict[str, str] = Field(description="Fields not sent explicitly: 'text' (parsed) or 'jev'")


class RankedCarrierOut(BaseModel):
    carrier: str
    total_cost: Decimal
    hq_distance_miles: Decimal | None
    hq_distance_source: str | None = Field(description="Where hq_distance_miles came from (see distance.source)")
    requested: bool = Field(description="The order description asks for this carrier")


class RejectionOut(BaseModel):
    carrier: str
    reasons: list[str]


class JevCallOut(BaseModel):
    step: str
    subject: str
    answer: str
    confidence: float
    elapsed_ms: int


class QuoteResponse(BaseModel):
    status: QuoteStatus
    carrier: str | None
    total_cost: Decimal | None
    currency: Literal["USD"] = "USD"
    requested_carrier: str | None = Field(description="Carrier the order description asks for (Jev), if any")
    distance: DistanceOut | None
    order: OrderOut
    ranking: list[RankedCarrierOut]
    rejected: list[RejectionOut]
    jev_calls: list[JevCallOut]
    warnings: list[str]
    explanation: str

    @classmethod
    def from_quote(cls, quote: Quote) -> QuoteResponse:
        d, o = quote.distance, quote.order
        return cls(
            status=quote.status,
            carrier=quote.selected.carrier.name if quote.selected else None,
            total_cost=quote.selected.total_cost if quote.selected else None,
            requested_carrier=quote.requested,
            distance=DistanceOut(miles=d.miles, source=d.source.value, approximate=d.approximate) if d else None,
            order=OrderOut(
                origin=o.origin,
                destination=o.destination,
                origin_state=o.origin_state,
                destination_state=o.destination_state,
                container_size=o.container_size,
                cargo_type=o.cargo_type,
                inferred=o.inferred,
            ),
            ranking=[
                RankedCarrierOut(
                    carrier=c.carrier.name,
                    total_cost=c.total_cost,
                    hq_distance_miles=c.hq_distance,
                    hq_distance_source=_source(quote.hq_distances.get(c.carrier.name)),
                    requested=c.requested,
                )
                for c in quote.ranking
            ],
            rejected=[RejectionOut(carrier=r.carrier_name, reasons=list(r.reasons)) for r in quote.rejected],
            jev_calls=[
                JevCallOut(
                    step=j.step, subject=j.subject, answer=j.answer, confidence=j.confidence, elapsed_ms=j.elapsed_ms
                )
                for j in quote.jev_calls
            ],
            warnings=list(quote.warnings),
            explanation=quote.explanation,
        )


def _source(result: DistanceResult | None) -> str | None:
    return result.source.value if result is not None else None
