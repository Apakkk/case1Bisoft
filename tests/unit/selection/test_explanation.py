"""The Turkish explanation is generated from the decision trace by templates (never by a model)."""

from decimal import Decimal

from app.selection.explanation import Outcome, explain
from app.selection.types import Rejection
from tests.case_data import CASE_ORDERS, decide, default_rules


def outcome_for(case_index: int, *, approximate: bool = False) -> Outcome:
    case = CASE_ORDERS[case_index]
    decided = decide(case.order)
    return Outcome(
        order=case.order,
        route_miles=decided.route_miles,
        distance_approximate=approximate,
        ranked=decided.ranked,
        rejected=decided.rejected,
        selected=decided.winner,
    )


def test_tie_explanation_names_the_deciding_criterion() -> None:
    text = explain(outcome_for(2), default_rules())  # order 3

    assert text.startswith("Rota Miami → Atlanta: 660 mil; 20 ft, Reefer.")
    assert "B-Logistics seçildi: toplam $660.00 (660 mil × $1.00/mil)." in text
    assert "Toplam ücret eşit; belirleyici kriter: merkezin çıkış noktasına uzaklığı" in text
    assert "B-Logistics: 30 mil (Fort Lauderdale), M-Logistics: 1190 mil (Houston)." in text


def test_price_explanation_mentions_runner_up() -> None:
    text = explain(outcome_for(1), default_rules())  # order 2

    assert "S-Logistics seçildi: toplam $94.00 (235 mil × $0.40/mil)." in text
    assert "Belirleyici kriter: toplam ücret — S-Logistics: $94.00, M-Logistics: $235.00." in text


def test_single_eligible_carrier() -> None:
    text = explain(outcome_for(0), default_rules())  # order 1

    assert "M-Logistics seçildi" in text
    assert "Tüm kısıtları sağlayan tek firma." in text


def test_no_carrier_lists_every_rejection() -> None:
    text = explain(outcome_for(5), default_rules())  # order 6

    assert "Uygun firma yok." in text
    for name in ("S-Logistics", "B-Logistics", "A-Logistics", "M-Logistics"):
        assert name in text
    assert "B-Logistics (45 ft konteyner taşımıyor (taşıdığı: 20 ft))" in text


def test_approximate_distance_is_flagged() -> None:
    text = explain(outcome_for(1, approximate=True), default_rules())

    assert "235 mil (yaklaşık)" in text


def test_note_rejection_is_explained_like_any_other_reason() -> None:
    base = outcome_for(6)  # order 7: only M-Logistics is eligible
    blocked = Outcome(
        order=base.order,
        route_miles=Decimal("85"),
        distance_approximate=False,
        ranked=(),
        rejected=(*base.rejected, Rejection("M-Logistics", ("Firma notu bu siparişi engelliyor",))),
        selected=None,
    )

    text = explain(blocked, default_rules())

    assert "Uygun firma yok." in text
    assert "M-Logistics (Firma notu bu siparişi engelliyor)" in text
