"""QuoteService orchestration with fakes: no database, no network, no Jev."""

from decimal import Decimal

import pytest

from app.clients.distance.chain import DistanceSource, UnknownLocationError
from app.models.carrier import Carrier
from app.models.quote import QuoteStatus
from app.schemas.quote import QuoteRequest
from app.selection.rules import RuleSet
from app.services.quote_service import InvalidOrderError, QuoteService
from tests.case_data import CASE_CARRIERS, CASE_ORDERS, CaseOrder, default_rules
from tests.fakes import InMemoryCarrierRepository, StaticRules, offline_distances


def service(carriers: tuple[Carrier, ...] = CASE_CARRIERS, rules: RuleSet | None = None) -> QuoteService:
    return QuoteService(InMemoryCarrierRepository(carriers), offline_distances(), StaticRules(rules or default_rules()))


def request(
    origin: str, destination: str, size: int | None, cargo: str | None, text: str | None = None
) -> QuoteRequest:
    return QuoteRequest(origin=origin, destination=destination, container_size=size, cargo_type=cargo, description=text)


@pytest.mark.parametrize("case", CASE_ORDERS, ids=lambda c: f"order-{c.id}")
def test_case_orders_through_the_service(case: CaseOrder) -> None:
    o = case.order
    quote = service().quote(request(o.origin, o.destination, o.container_size, o.cargo_type))

    if case.expected_carrier is None:
        assert quote.status is QuoteStatus.NO_CARRIER
        assert quote.selected is None
        assert len(quote.rejected) == 4
    else:
        assert quote.status is QuoteStatus.SELECTED
        assert quote.selected is not None
        assert (quote.selected.carrier.name, quote.selected.total_cost) == (case.expected_carrier, case.expected_cost)
    assert quote.distance is not None and quote.distance.source is DistanceSource.CASE_TABLE
    assert quote.explanation.startswith(f"Rota {o.origin} → {o.destination}")


def test_input_is_normalized() -> None:
    quote = service().quote(request(" miami ", "Ft. Lauderdale", 40, "reefer"))

    assert (quote.order.origin, quote.order.destination, quote.order.cargo_type) == (
        "Miami",
        "Fort Lauderdale",
        "Reefer",
    )
    assert quote.selected is not None and quote.selected.carrier.name == "M-Logistics"


def test_container_size_is_parsed_from_text_before_any_model() -> None:
    quote = service().quote(request("Miami", "Atlanta", None, "Reefer", "two pallets in a 20'lik konteyner"))

    assert quote.order.container_size == 20
    assert quote.order.inferred == {"container_size": "text"}
    assert quote.selected is not None and quote.selected.carrier.name == "B-Logistics"


def test_missing_field_without_jev_asks_for_input() -> None:
    quote = service().quote(request("Miami", "Atlanta", 20, None, "frozen shrimp"))

    assert quote.status is QuoteStatus.NEEDS_INPUT
    assert quote.selected is None
    assert "yük tipi belirlenemedi" in quote.explanation


@pytest.mark.parametrize(
    ("size", "cargo", "message"),
    [
        (53, "Dry", "container_size 53 is not carried by any carrier"),
        (40, "Flatrack", "cargo_type 'Flatrack' is not in the catalog"),
        (None, "Dry", "describe the cargo"),
    ],
)
def test_orders_outside_the_catalog_are_rejected(size: int | None, cargo: str, message: str) -> None:
    with pytest.raises(InvalidOrderError, match=message):
        service().quote(request("Miami", "Atlanta", size, cargo))


def test_a_size_one_carrier_carries_is_valid_for_orders_and_read_from_text() -> None:
    k53 = Carrier("K-Logistics", "Miami", None, None, frozenset({53}), frozenset({"Dry"}), Decimal("1.00"))
    carriers = service((*CASE_CARRIERS, k53))

    entered = carriers.quote(request("Miami", "Orlando", 53, "Dry"))
    parsed = carriers.quote(request("Miami", "Orlando", None, "Dry", "53 ft konteyner"))

    for quote in (entered, parsed):
        assert quote.selected is not None and quote.selected.carrier.name == "K-Logistics"
    assert parsed.order.inferred == {"container_size": "text"}


def test_new_cargo_type_only_needs_a_catalog_entry() -> None:
    rules = default_rules(catalog={"cargo_types": ["Dry", "Reefer", "Hazardous", "Flatrack"], "container_sizes": [40]})

    quote = service(rules=rules).quote(request("Miami", "Atlanta", 40, "flatrack"))

    assert quote.status is QuoteStatus.NO_CARRIER  # valid order, nobody carries it yet
    assert all("Flatrack yük taşımıyor" in " ".join(r.reasons) for r in quote.rejected)


def test_approximate_distance_near_a_limit_needs_review() -> None:
    quote = service().quote(request("Tampa", "Miami", 20, "Dry"))  # off-table: Haversine ~247 mi

    assert quote.distance is not None and quote.distance.approximate
    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert any("B-Logistics alt sınırına (250 mil) yakın" in w for w in quote.warnings)


def test_unknown_origin_is_an_error() -> None:
    with pytest.raises(UnknownLocationError):
        service().quote(request("Atlantis", "Miami", 20, "Dry"))


def test_unknown_hq_city_is_ranked_last_with_a_warning() -> None:
    nowhere = Carrier("Z-Logistics", "Nowhere", None, None, frozenset({20}), frozenset({"Reefer"}), Decimal("1.00"))

    quote = service((*CASE_CARRIERS, nowhere)).quote(request("Miami", "Atlanta", 20, "Reefer"))

    assert [c.carrier.name for c in quote.ranking] == ["B-Logistics", "M-Logistics", "Z-Logistics"]
    assert any("Z-Logistics merkezi (Nowhere) bulunamadı" in w for w in quote.warnings)


def test_an_approximate_hq_distance_says_so_and_keeps_its_source() -> None:
    # Miami -> Orlando is in the table; S's HQ (Tampa) -> Miami is not, and there is no routing service here.
    quote = service().quote(request("Miami", "Orlando", 40, "Dry"))

    assert quote.distance is not None and quote.distance.source is DistanceSource.CASE_TABLE
    assert quote.hq_distances["S-Logistics"].source is DistanceSource.HAVERSINE
    assert quote.hq_distances["M-Logistics"].source is DistanceSource.CASE_TABLE  # Houston - Miami: 1190
    assert "S-Logistics merkezi (Tampa) → Miami mesafesi yaklaşık: kuş uçuşu × 1.2." in quote.warnings
    assert quote.status is QuoteStatus.SELECTED  # ranking data only: no review needed


def test_cities_are_resolved_with_their_state() -> None:
    quote = service().quote(request("miami, florida", "ATLANTA", 20, "Reefer"))

    assert (quote.order.origin, quote.order.origin_state) == ("Miami", "FL")
    assert (quote.order.destination, quote.order.destination_state) == ("Atlanta", "GA")


def test_a_rules_file_problem_is_reported_with_the_quote() -> None:
    rules = StaticRules(default_rules())
    rules.problem = "rules.yaml geçersiz (unknown ranking criterion 'totl_cost'); son geçerli kurallar kullanılıyor."
    quotes = QuoteService(InMemoryCarrierRepository(CASE_CARRIERS), offline_distances(), rules)

    quote = quotes.quote(request("Miami", "Atlanta", 20, "Reefer"))

    assert quote.status is QuoteStatus.SELECTED  # a configuration problem, not a doubt about this order
    assert rules.problem in quote.warnings


def test_a_limit_of_a_carrier_that_fails_another_constraint_does_not_need_review() -> None:
    # Haversine ~292 mi, near S-Logistics' 300 limit, but S-Logistics does not carry Hazardous anyway.
    quote = service().quote(request("Miami", "Daytona Beach", 40, "Hazardous"))

    assert quote.distance is not None and quote.distance.approximate
    assert quote.status is QuoteStatus.SELECTED
    assert not any("S-Logistics" in w for w in quote.warnings)
