"""Carrier notes are pre-checked by Jev once, when saved; only confident 'no restriction' skips later checks."""

from decimal import Decimal

import pytest

from app.models.carrier import NoteStatus
from app.schemas.carrier import CarrierIn
from app.services.carrier_service import CarrierService
from tests.case_data import default_rules
from tests.fakes import FakeJev, InMemoryCarrierRepository, StaticRules, offline_distances


def carrier_in(description: str) -> CarrierIn:
    return CarrierIn(
        name="K-Logistics",
        hq_city="Orlando",
        container_sizes=[20],
        cargo_types=["Dry"],
        rate_per_mile=Decimal("1.00"),
        description=description,
    )


def service(jev: FakeJev | None) -> CarrierService:
    return CarrierService(InMemoryCarrierRepository(), offline_distances(), StaticRules(default_rules()), jev)


@pytest.mark.parametrize(
    ("p_restriction", "status"),
    [(0.05, NoteStatus.NONE), (0.50, NoteStatus.CONSTRAINT), (0.92, NoteStatus.CONSTRAINT)],
)
def test_note_is_classified_once_when_saved(p_restriction: float, status: NoteStatus) -> None:
    jev = FakeJev(restriction=p_restriction)

    carrier = service(jev).create(carrier_in("Hafta sonu çalışmıyoruz."))

    assert (carrier.note_status, carrier.note_confidence) == (status, p_restriction)
    assert jev.calls == ["note_has_restriction"]


def test_empty_note_needs_no_check() -> None:
    jev = FakeJev()

    assert service(jev).create(carrier_in("")).note_status is NoteStatus.NONE
    assert jev.calls == []


def test_unchanged_note_is_not_checked_again() -> None:
    jev = FakeJev(restriction=0.9)
    carriers = service(jev)
    created = carriers.create(carrier_in("No hazmat."))
    assert created.id is not None

    updated = carriers.update(created.id, carrier_in("No hazmat.").model_copy(update={"rate_per_mile": Decimal("2")}))

    assert jev.calls == ["note_has_restriction"]
    assert updated.note_status is NoteStatus.CONSTRAINT


@pytest.mark.parametrize("jev", [FakeJev(fail=True), None], ids=["jev-down", "no-jev"])
def test_note_without_an_answer_is_unchecked(jev: FakeJev | None) -> None:
    assert service(jev).create(carrier_in("No hazmat.")).note_status is NoteStatus.UNCHECKED
