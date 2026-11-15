from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.models.carrier import Carrier, NoteStatus
from app.repositories.carrier_repository import (
    DuplicateCarrierError,
    InvalidCarrierError,
    PostgresCarrierRepository,
)
from tests.case_data import CASE_CARRIERS, CASE_ORDERS, CaseOrder, decide

pytestmark = pytest.mark.db

NEW = Carrier(
    name="K-Logistics",
    hq_city="Orlando",
    min_miles=Decimal("10"),
    max_miles=Decimal("500.5"),
    container_sizes=frozenset({20, 40}),
    cargo_types=frozenset({"Dry", "Reefer"}),
    rate_per_mile=Decimal("0.375"),
    description="Hafta sonu çalışmıyoruz.",
    note_status=NoteStatus.CONSTRAINT,
    note_confidence=0.912,
)


def without_id(carrier: Carrier) -> Carrier:
    return replace(carrier, id=None)


def test_seed_contains_exactly_the_case_carriers(carriers: PostgresCarrierRepository) -> None:
    stored = {c.name: replace(without_id(c), description="") for c in carriers.list()}

    assert stored == {c.name: c for c in CASE_CARRIERS}


@pytest.mark.parametrize("case", CASE_ORDERS, ids=lambda c: f"order-{c.id}")
def test_seeded_carriers_produce_the_expected_results(carriers: PostgresCarrierRepository, case: CaseOrder) -> None:
    winner = decide(case.order, carriers=carriers.list()).winner

    assert (winner.carrier.name if winner else None) == case.expected_carrier


def test_create_get_update_delete_round_trip(carriers: PostgresCarrierRepository) -> None:
    created = carriers.create(NEW)
    assert created.id is not None
    assert without_id(created) == NEW  # Decimal, arrays, enum and float survive the round trip

    assert carriers.get(created.id) == created

    updated = carriers.update(created.id, replace(NEW, rate_per_mile=Decimal("0.50"), max_miles=None))
    assert updated is not None
    assert (updated.rate_per_mile, updated.max_miles) == (Decimal("0.50"), None)

    assert carriers.delete(created.id) is True
    assert carriers.get(created.id) is None
    assert carriers.delete(created.id) is False


def test_update_of_missing_carrier_returns_none(carriers: PostgresCarrierRepository) -> None:
    assert carriers.update(999_999, NEW) is None


def test_names_are_unique_ignoring_case(carriers: PostgresCarrierRepository) -> None:
    with pytest.raises(DuplicateCarrierError):
        carriers.create(replace(NEW, name="m-logistics"))


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({"min_miles": Decimal("600"), "max_miles": Decimal("100")}, "carriers_miles_range"),
        ({"rate_per_mile": Decimal("0")}, "carriers_rate_positive"),
        ({"container_sizes": frozenset()}, "carriers_sizes_not_empty"),
        ({"name": "   "}, "carriers_name_not_blank"),
    ],
)
def test_database_check_constraints_are_the_safety_net(
    carriers: PostgresCarrierRepository, change: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(InvalidCarrierError) as error:
        carriers.create(replace(NEW, **change))

    assert error.value.constraint == constraint
    assert len(carriers.list()) == 4  # the failed insert rolled back to its savepoint
