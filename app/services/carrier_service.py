"""Carrier CRUD shared by the JSON API and the admin screen: one place for validation."""

from app.clients.distance.chain import DistanceProvider
from app.clients.jev_client import JevClient, JevUnavailableError
from app.models.carrier import Carrier, NoteStatus
from app.repositories.carrier_repository import CarrierRepository
from app.repositories.rules_repository import RulesSource
from app.schemas.carrier import CarrierIn


class CarrierNotFoundError(LookupError):
    def __init__(self, carrier_id: int) -> None:
        super().__init__(f"carrier {carrier_id} not found")
        self.carrier_id = carrier_id


class CarrierValidationError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class CarrierService:
    def __init__(
        self,
        carriers: CarrierRepository,
        distances: DistanceProvider,
        rules: RulesSource,
        jev: JevClient | None = None,
    ) -> None:
        self._carriers = carriers
        self._distances = distances
        self._rules = rules
        self._jev = jev

    def list(self) -> list[Carrier]:
        return self._carriers.list()

    def get(self, carrier_id: int) -> Carrier:
        carrier = self._carriers.get(carrier_id)
        if carrier is None:
            raise CarrierNotFoundError(carrier_id)
        return carrier

    def create(self, data: CarrierIn) -> Carrier:
        return self._carriers.create(self._build(data, existing=None))

    def update(self, carrier_id: int, data: CarrierIn) -> Carrier:
        existing = self.get(carrier_id)
        updated = self._carriers.update(carrier_id, self._build(data, existing=existing))
        if updated is None:
            raise CarrierNotFoundError(carrier_id)
        return updated

    def delete(self, carrier_id: int) -> None:
        if not self._carriers.delete(carrier_id):
            raise CarrierNotFoundError(carrier_id)

    def _build(self, data: CarrierIn, existing: Carrier | None) -> Carrier:
        rules = self._rules.get()
        errors: dict[str, str] = {}

        unknown_sizes = sorted(set(data.container_sizes) - set(rules.container_sizes))
        if unknown_sizes:
            errors["container_sizes"] = (
                f"not in the catalog: {', '.join(map(str, unknown_sizes))} "
                f"(allowed: {', '.join(map(str, rules.container_sizes))})"
            )

        cargo_types: set[str] = set()
        for raw in data.cargo_types:
            canonical = rules.canonical_cargo_type(raw)
            if canonical is None:
                errors["cargo_types"] = f"'{raw}' is not in the catalog (allowed: {', '.join(rules.cargo_types)})"
            else:
                cargo_types.add(canonical)

        if errors:
            raise CarrierValidationError(errors)

        note_status, note_confidence = self._note_status(data.description, existing)
        return Carrier(
            name=data.name,
            hq_city=self._distances.normalize(data.hq_city),
            min_miles=data.min_miles,
            max_miles=data.max_miles,
            container_sizes=frozenset(data.container_sizes),
            cargo_types=frozenset(cargo_types),
            rate_per_mile=data.rate_per_mile,
            description=data.description,
            note_status=note_status,
            note_confidence=note_confidence,
        )

    def _note_status(self, description: str, existing: Carrier | None) -> tuple[NoteStatus, float | None]:
        """Pre-check a changed note once at save time, so quotes only ask Jev about notes that may restrict.

        Conservative: only a confident "no restriction" skips the per-order check later.
        """
        if not description:
            return NoteStatus.NONE, None
        if existing is not None and existing.description == description:
            return existing.note_status, existing.note_confidence  # unchanged text: keep the earlier check
        if self._jev is None:
            return NoteStatus.UNCHECKED, None
        try:
            p = self._jev.note_has_restriction(description).restriction_probability
        except JevUnavailableError:
            return NoteStatus.UNCHECKED, None
        no_restriction = p <= 1 - self._rules.get().confidence.auto_accept
        return (NoteStatus.NONE if no_restriction else NoteStatus.CONSTRAINT), round(p, 3)
