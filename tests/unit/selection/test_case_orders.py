"""The seven test orders from the case, end to end through the pure selection module."""

import pytest

from tests.case_data import CASE_ORDERS, CaseOrder, decide


@pytest.mark.parametrize("case", CASE_ORDERS, ids=lambda c: f"order-{c.id}")
def test_case_order_selects_expected_carrier(case: CaseOrder) -> None:
    decided = decide(case.order)

    if case.expected_carrier is None:
        assert decided.winner is None
    else:
        assert decided.winner is not None
        assert decided.winner.carrier.name == case.expected_carrier
        assert decided.winner.total_cost == case.expected_cost


def test_order_3_tie_is_broken_by_hq_proximity_to_origin() -> None:
    decided = decide(CASE_ORDERS[2].order)  # Miami -> Atlanta, 20 ft Reefer

    b, m = decided.ranked
    assert b.total_cost == m.total_cost == 660
    assert (b.carrier.name, b.hq_distance) == ("B-Logistics", 30)  # Fort Lauderdale - Miami
    assert (m.carrier.name, m.hq_distance) == ("M-Logistics", 1190)  # Houston - Miami


def test_order_6_reports_every_reason_for_every_carrier() -> None:
    decided = decide(CASE_ORDERS[5].order)  # Miami -> Houston (1190 mi), 45 ft Reefer

    reasons = {r.carrier_name: r.reasons for r in decided.rejected}
    assert reasons == {
        "S-Logistics": ("Mesafe 1190 mil, üst sınır 300 mil", "Reefer yük taşımıyor (taşıdığı: Dry)"),
        "B-Logistics": ("45 ft konteyner taşımıyor (taşıdığı: 20 ft)",),
        "A-Logistics": ("Mesafe 1190 mil, üst sınır 200 mil", "Reefer yük taşımıyor (taşıdığı: Dry, Hazardous)"),
        "M-Logistics": ("45 ft konteyner taşımıyor (taşıdığı: 20, 40 ft)",),
    }
