from decimal import Decimal

from app.selection.engine import boundary_warnings
from tests.case_data import CASE_CARRIERS

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
