"""Lexicographic ranking: a criterion only matters when every criterion above it is exactly equal."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.models.carrier import Carrier
from app.models.order import Order
from app.selection.engine import rank, with_requested
from app.selection.rules import RulesError
from tests.case_data import CASE_CARRIERS, M_LOGISTICS, case_distance, decide, default_rules

D = Decimal

# A Miami-based, expensive carrier: only wins when proximity outranks price.
X_LOGISTICS = Carrier("X-Logistics", "Miami", None, None, frozenset({40}), frozenset({"Dry"}), D("3.00"))
MIAMI_ORLANDO_40_DRY = Order("Miami", "Orlando", 40, "Dry")


def hq_distance_with_tampa(a: str, b: str) -> Decimal | None:
    if {a, b} == {"Tampa", "Miami"}:
        return D("280")
    return case_distance(a, b)


def test_default_rules_rank_price_first() -> None:
    decided = decide(MIAMI_ORLANDO_40_DRY, carriers=(*CASE_CARRIERS, X_LOGISTICS), hq_distance=hq_distance_with_tampa)

    assert [c.carrier.name for c in decided.ranked] == ["S-Logistics", "M-Logistics", "X-Logistics"]


def test_putting_price_second_is_a_config_change() -> None:
    rules = default_rules(ranking=["hq_proximity", "total_cost"])

    decided = decide(
        MIAMI_ORLANDO_40_DRY,
        carriers=(*CASE_CARRIERS, X_LOGISTICS),
        rules=rules,
        hq_distance=hq_distance_with_tampa,
    )

    assert decided.winner is not None
    assert decided.winner.carrier.name == "X-Logistics"  # HQ in Miami: 0 mi from origin
    assert decided.winner.total_cost == D("705.00")


def test_one_cent_cheaper_wins_regardless_of_proximity() -> None:
    far_cheap = replace(M_LOGISTICS, name="Far-Cheap", rate_per_mile=D("0.99"))
    near_pricey = replace(M_LOGISTICS, name="Near-Pricey", hq_city="Miami", rate_per_mile=D("1.00"))

    decided = decide(
        Order("Miami", "Atlanta", 20, "Reefer"),
        carriers=(near_pricey, far_cheap),
        hq_distance=lambda a, b: D("0") if a == b else D("1190"),
    )

    assert [c.carrier.name for c in decided.ranked] == ["Far-Cheap", "Near-Pricey"]


def test_full_tie_falls_back_to_carrier_name() -> None:
    zeta = replace(M_LOGISTICS, name="Zeta")
    alpha = replace(M_LOGISTICS, name="Alpha")

    decided = decide(Order("Miami", "Atlanta", 20, "Reefer"), carriers=(zeta, alpha))

    assert [c.carrier.name for c in decided.ranked] == ["Alpha", "Zeta"]


def test_unknown_hq_distance_ranks_after_known_ones() -> None:
    unknown = replace(M_LOGISTICS, name="A-Unknown", hq_city="Nowhere")

    decided = decide(Order("Miami", "Atlanta", 20, "Reefer"), carriers=(unknown, M_LOGISTICS))

    assert [c.carrier.name for c in decided.ranked] == ["M-Logistics", "A-Unknown"]
    assert decided.ranked[1].hq_distance is None


def test_name_is_always_the_final_tie_breaker() -> None:
    assert default_rules(ranking=["total_cost"]).ranking == ("total_cost", "name")


def test_hq_distances_are_skipped_when_proximity_is_not_ranked() -> None:
    calls: list[tuple[str, str]] = []

    def spy(a: str, b: str) -> Decimal | None:
        calls.append((a, b))
        return None

    decide(Order("Miami", "Orlando", 40, "Dry"), rules=default_rules(ranking=["total_cost"]), hq_distance=spy)

    assert calls == []


def test_requested_carrier_comes_before_a_cheaper_one() -> None:
    eligible = decide(MIAMI_ORLANDO_40_DRY).ranked  # S-Logistics $94, M-Logistics $235

    ranked = rank(with_requested(eligible, "M-Logistics"), default_rules())

    assert [c.carrier.name for c in ranked] == ["M-Logistics", "S-Logistics"]


def test_requested_carrier_comes_first_whatever_the_rules_order_the_others() -> None:
    rules = default_rules(ranking=["hq_proximity", "total_cost"])
    eligible = decide(MIAMI_ORLANDO_40_DRY, rules=rules, hq_distance=hq_distance_with_tampa).ranked
    assert [c.carrier.name for c in eligible] == ["S-Logistics", "M-Logistics"]  # Tampa is closer than Houston

    ranked = rank(with_requested(eligible, "M-Logistics"), rules)

    assert [c.carrier.name for c in ranked] == ["M-Logistics", "S-Logistics"]


def test_requested_is_not_a_configurable_rule() -> None:
    with pytest.raises(RulesError, match="unknown ranking criterion 'requested'"):
        default_rules(ranking=["requested", "total_cost"])
