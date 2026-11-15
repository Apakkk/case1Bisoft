"""Distance limits are inclusive (<=, >=); an unset limit means unbounded."""

from decimal import Decimal

import pytest

from app.models.order import Order
from tests.case_data import A_LOGISTICS, B_LOGISTICS, M_LOGISTICS, S_LOGISTICS, decide


def eligible_names(miles: str, size: int, cargo: str = "Dry") -> set[str]:
    decided = decide(Order("X", "Y", size, cargo), route_miles=Decimal(miles), hq_distance=lambda a, b: None)
    return {c.carrier.name for c in decided.ranked}


@pytest.mark.parametrize(
    ("miles", "expected"),
    [("200", True), ("200.1", False)],
)
def test_a_logistics_max_200_is_inclusive(miles: str, expected: bool) -> None:
    assert (A_LOGISTICS.name in eligible_names(miles, 45)) is expected


@pytest.mark.parametrize(
    ("miles", "expected"),
    [("249.9", False), ("250", True)],
)
def test_b_logistics_min_250_is_inclusive(miles: str, expected: bool) -> None:
    assert (B_LOGISTICS.name in eligible_names(miles, 20)) is expected


@pytest.mark.parametrize(
    ("miles", "expected"),
    [("300", True), ("300.1", False)],
)
def test_s_logistics_max_300_is_inclusive(miles: str, expected: bool) -> None:
    assert (S_LOGISTICS.name in eligible_names(miles, 40)) is expected


@pytest.mark.parametrize("miles", ["0", "1", "5000"])
def test_m_logistics_has_no_distance_limit(miles: str) -> None:
    assert M_LOGISTICS.name in eligible_names(miles, 40)
