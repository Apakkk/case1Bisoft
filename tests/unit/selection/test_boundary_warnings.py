from decimal import Decimal

from app.models.order import Order
from app.selection.engine import boundary_warnings, distance_sensitive
from tests.case_data import CASE_CARRIERS, default_rules

RATIO = Decimal("0.10")


def test_approximate_distance_near_a_limit_is_flagged() -> None:
    warnings = boundary_warnings(CASE_CARRIERS, Decimal("246.8"), RATIO)

    # within 10% of B's 250 min, A's 200 max is 23% away, S's 300 max is 18% away
    assert warnings == (
        "Yaklaşık mesafe (246.8 mil) B-Logistics alt sınırına (250 mil) yakın; gerçek mesafeyle karar değişebilir.",
    )


def test_distance_far_from_every_limit_is_not_flagged() -> None:
    assert boundary_warnings(CASE_CARRIERS, Decimal("1000"), RATIO) == ()


def test_unbounded_carrier_never_warns() -> None:
    m_logistics = CASE_CARRIERS[3]

    assert boundary_warnings([m_logistics], Decimal("1"), RATIO) == ()


def test_only_carriers_that_pass_every_other_constraint_are_distance_sensitive() -> None:
    order = Order("Miami", "Daytona Beach", 40, "Hazardous")

    sensitive = distance_sensitive(CASE_CARRIERS, order, Decimal("292.4"), default_rules())

    # S: no Hazardous; B: no 40 ft, no Hazardous; A: no 40 ft. Their limits cannot change this result.
    assert [c.name for c in sensitive] == ["M-Logistics"]


def test_a_carrier_out_only_by_distance_stays_distance_sensitive() -> None:
    order = Order("Tampa", "Miami", 20, "Dry")

    sensitive = distance_sensitive(CASE_CARRIERS, order, Decimal("246.8"), default_rules())

    # B fails only its 250 mile minimum: the real distance could make it eligible.
    assert [c.name for c in sensitive] == ["B-Logistics", "M-Logistics"]
