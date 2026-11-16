"""API DTOs for carriers. Cargo types must be in the catalog (CarrierService); container sizes are free."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.carrier import Carrier, NoteStatus
from app.selection.catalog import MAX_CONTAINER_FT

ContainerFt = Annotated[int, Field(gt=0, le=MAX_CONTAINER_FT)]


class CarrierIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["K-Logistics"])
    hq_city: str = Field(min_length=1, max_length=100, examples=["Orlando"])
    min_miles: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=1, description="None = no limit")
    max_miles: Decimal | None = Field(default=None, ge=0, max_digits=8, decimal_places=1, description="None = no limit")
    container_sizes: list[ContainerFt] = Field(
        min_length=1, examples=[[20, 40]], description="Feet; any size (1-99), not only the standard ones"
    )
    cargo_types: list[str] = Field(min_length=1, examples=[["Dry", "Reefer"]])
    rate_per_mile: Decimal = Field(gt=0, max_digits=10, decimal_places=4, examples=["0.85"])
    description: str = Field(default="", max_length=2000, description="Free text; restrictions are checked by Jev")

    @field_validator("name", "hq_city", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("name", "hq_city")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("container_sizes")
    @classmethod
    def _unique_sizes(cls, value: list[int]) -> list[int]:
        return sorted(set(value))

    @model_validator(mode="after")
    def _range(self) -> "CarrierIn":
        if self.min_miles is not None and self.max_miles is not None and self.min_miles > self.max_miles:
            raise ValueError("min_miles must be less than or equal to max_miles")
        return self


class CarrierOut(BaseModel):
    id: int
    name: str
    hq_city: str
    min_miles: Decimal | None
    max_miles: Decimal | None
    container_sizes: list[int]
    cargo_types: list[str]
    rate_per_mile: Decimal
    description: str
    note_status: NoteStatus
    note_confidence: float | None

    @classmethod
    def from_carrier(cls, carrier: Carrier) -> "CarrierOut":
        assert carrier.id is not None
        return cls(
            id=carrier.id,
            name=carrier.name,
            hq_city=carrier.hq_city,
            min_miles=carrier.min_miles,
            max_miles=carrier.max_miles,
            container_sizes=sorted(carrier.container_sizes),
            cargo_types=sorted(carrier.cargo_types),
            rate_per_mile=carrier.rate_per_mile,
            description=carrier.description,
            note_status=carrier.note_status,
            note_confidence=carrier.note_confidence,
        )
