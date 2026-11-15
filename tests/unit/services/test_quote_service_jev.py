"""Where Jev enters the quote flow, and what happens when it is unsure or unavailable (FakeJev only)."""

from dataclasses import replace
from decimal import Decimal

from app.models.carrier import Carrier, NoteStatus
from app.models.quote import QuoteStatus
from app.schemas.quote import QuoteRequest
from app.services.quote_service import QuoteService
from tests.case_data import B_LOGISTICS, CASE_CARRIERS, M_LOGISTICS, S_LOGISTICS, default_rules
from tests.fakes import FakeJev, InMemoryCarrierRepository, StaticRules, choice, offline_distances

NO_HAZMAT = "Şu an tehlikeli yük kabul etmiyoruz."


def service(jev: FakeJev | None, carriers: tuple[Carrier, ...] = CASE_CARRIERS) -> QuoteService:
    return QuoteService(InMemoryCarrierRepository(carriers), offline_distances(), StaticRules(default_rules()), jev)


def with_note(carrier: Carrier, note: str, status: NoteStatus = NoteStatus.CONSTRAINT) -> Carrier:
    return replace(carrier, description=note, note_status=status)


def replace_carrier(carrier: Carrier) -> tuple[Carrier, ...]:
    return tuple(carrier if c.name == carrier.name else c for c in CASE_CARRIERS)


def miami_atlanta(**fields: object) -> QuoteRequest:
    return QuoteRequest.model_validate({"origin": "Miami", "destination": "Atlanta", **fields})


# --- free-text order interpretation -------------------------------------------------------


def test_structured_orders_without_a_description_never_call_jev() -> None:
    jev = FakeJev()

    service(jev).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert jev.calls == []


def test_confident_classification_is_used() -> None:
    jev = FakeJev(cargo=choice("Reefer", 0.95, Dry=0.04, Reefer=0.95, Hazardous=0.01))

    quote = service(jev).quote(miami_atlanta(container_size=20, description="frozen shrimp"))

    assert quote.status is QuoteStatus.SELECTED
    assert quote.order.cargo_type == "Reefer"
    assert quote.order.inferred == {"cargo_type": "jev"}
    assert quote.selected is not None and quote.selected.carrier.name == "B-Logistics"
    assert [(c.step, c.subject, c.answer) for c in quote.jev_calls] == [
        ("cargo_type", "frozen shrimp", "Reefer"),
        ("requested_carrier", "frozen shrimp", "no_specific_carrier"),
        ("compatibility", "B-Logistics", "compatible"),
        ("compatibility", "M-Logistics", "compatible"),
    ]


def test_medium_confidence_computes_but_needs_review() -> None:
    jev = FakeJev(cargo=choice("Reefer", 0.72, Dry=0.25, Reefer=0.72, Hazardous=0.03))

    quote = service(jev).quote(miami_atlanta(container_size=20, description="seafood"))

    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert quote.selected is not None
    assert any("Yük tipi Jev ile düşük güvenle belirlendi (Reefer, güven 0.72)" in w for w in quote.warnings)


def test_low_confidence_is_never_guessed() -> None:
    jev = FakeJev(cargo=choice("Dry", 0.41, Dry=0.45, Reefer=0.40, Hazardous=0.15))

    quote = service(jev).quote(miami_atlanta(container_size=20, description="mixed goods"))

    assert quote.status is QuoteStatus.NEEDS_INPUT
    assert quote.selected is None
    assert "yük tipi belirlenemedi" in quote.explanation
    assert any("tahmin edilmedi" in w for w in quote.warnings)


def test_possible_hazardous_cargo_triggers_review_even_when_another_label_wins() -> None:
    jev = FakeJev(cargo=choice("Dry", 0.90, Dry=0.78, Reefer=0.02, Hazardous=0.20))

    quote = service(jev).quote(miami_atlanta(container_size=20, description="cleaning supplies"))

    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert any("Tehlikeli yük olasılığı 0.20" in w for w in quote.warnings)


def test_size_and_cargo_are_asked_in_a_single_request() -> None:
    jev = FakeJev(size=choice("40", 0.93), cargo=choice("Dry", 0.97))

    quote = service(jev).quote(QuoteRequest(origin="Miami", destination="Orlando", description="office chairs"))

    assert jev.calls == ["classify_order", "check_compatibility"]  # one request each, never one per field
    assert quote.order.inferred == {"container_size": "jev", "cargo_type": "jev"}
    assert quote.selected is not None and quote.selected.carrier.name == "S-Logistics"


def test_jev_outage_asks_for_input_instead_of_failing() -> None:
    quote = service(FakeJev(fail=True)).quote(miami_atlanta(container_size=20, description="frozen shrimp"))

    assert quote.status is QuoteStatus.NEEDS_INPUT
    assert any("Jev'e ulaşılamadı" in w for w in quote.warnings)


# --- carrier notes --------------------------------------------------------------------------


def test_blocking_note_removes_the_only_eligible_carrier() -> None:
    jev = FakeJev(blocks={"M-Logistics": 0.97})
    carriers = replace_carrier(with_note(M_LOGISTICS, NO_HAZMAT))

    quote = service(jev, carriers).quote(
        QuoteRequest(origin="Tampa", destination="Orlando", container_size=20, cargo_type="Hazardous")  # order 7
    )

    assert quote.status is QuoteStatus.NO_CARRIER
    m = next(r for r in quote.rejected if r.carrier_name == "M-Logistics")
    assert m.reasons == (f'Firma notu bu siparişi engelliyor: "{NO_HAZMAT}" (Jev, olasılık 0.97)',)
    assert "Uygun firma yok." in quote.explanation


def test_blocking_note_on_the_winner_promotes_the_runner_up() -> None:
    jev = FakeJev(blocks={"B-Logistics": 0.95})
    carriers = replace_carrier(with_note(B_LOGISTICS, "No Atlanta deliveries until December."))

    quote = service(jev, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))  # order 3

    assert quote.selected is not None and quote.selected.carrier.name == "M-Logistics"
    assert quote.status is QuoteStatus.SELECTED
    assert [c.carrier.name for c in quote.ranking] == ["M-Logistics"]


def test_uncertain_note_on_the_winner_needs_review() -> None:
    jev = FakeJev(blocks={"B-Logistics": 0.55})
    carriers = replace_carrier(with_note(B_LOGISTICS, "Limited reefer capacity this week."))

    quote = service(jev, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert quote.selected is not None and quote.selected.carrier.name == "B-Logistics"
    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert any("B-Logistics notunun bu siparişe etkisi belirsiz" in w for w in quote.warnings)


def test_harmless_note_is_allowed() -> None:
    jev = FakeJev(blocks={"B-Logistics": 0.04})
    carriers = replace_carrier(with_note(B_LOGISTICS, "Hafta sonu çalışmıyoruz."))

    quote = service(jev, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.SELECTED, "B-Logistics")


def test_notes_prechecked_as_harmless_are_not_sent_to_jev() -> None:
    jev = FakeJev()
    carriers = replace_carrier(with_note(B_LOGISTICS, "24/7 dispatch.", NoteStatus.NONE))

    service(jev, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert jev.calls == []


def test_all_candidate_notes_go_in_one_request() -> None:
    jev = FakeJev()
    carriers = (with_note(B_LOGISTICS, "Note B."), with_note(M_LOGISTICS, "Note M.", NoteStatus.UNCHECKED))

    service(jev, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert jev.calls == ["check_compatibility"]
    assert jev.notes_asked == [{"B-Logistics": "Note B.", "M-Logistics": "Note M."}]


def test_jev_outage_during_note_check_needs_review_and_keeps_the_ranking() -> None:
    carriers = replace_carrier(with_note(B_LOGISTICS, "Limited reefer capacity."))

    quote = service(FakeJev(fail=True), carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert quote.selected is not None and quote.selected.carrier.name == "B-Logistics"
    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert any("firma notları kontrol edilmedi: B-Logistics" in w for w in quote.warnings)


def test_without_jev_configured_restrictive_notes_need_review() -> None:
    carriers = replace_carrier(with_note(B_LOGISTICS, "Limited reefer capacity."))

    quote = service(None, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert quote.status is QuoteStatus.NEEDS_REVIEW


# --- order description vs carrier descriptions ----------------------------------------------

DONT_USE_S = "s logistics ile çalışmak istemiyorum"


def miami_orlando(description: str) -> QuoteRequest:  # order 2: S-Logistics $94, M-Logistics $235
    return QuoteRequest(
        origin="Miami", destination="Orlando", container_size=40, cargo_type="Dry", description=description
    )


def test_order_description_excluding_the_winner_removes_it() -> None:
    jev = FakeJev(blocks={"S-Logistics": 0.97, "M-Logistics": 0.03})

    quote = service(jev).quote(miami_orlando(DONT_USE_S))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.SELECTED, "M-Logistics")
    assert quote.selected is not None and quote.selected.total_cost == Decimal("235.00")
    s = next(r for r in quote.rejected if r.carrier_name == "S-Logistics")
    assert s.reasons == (f'Sipariş açıklamasıyla uyumsuz: "{DONT_USE_S}" (Jev, olasılık 0.97)',)
    assert "S-Logistics (Sipariş açıklamasıyla uyumsuz" in quote.explanation


def test_order_description_is_compared_with_every_eligible_carrier_in_one_request() -> None:
    jev = FakeJev()
    carriers = replace_carrier(with_note(S_LOGISTICS, "Dry cargo in Florida.", NoteStatus.NONE))

    service(jev, carriers).quote(miami_orlando(DONT_USE_S))

    assert jev.calls == ["check_compatibility"]
    assert jev.order_notes == [DONT_USE_S]
    assert jev.notes_asked == [{"S-Logistics": "Dry cargo in Florida.", "M-Logistics": ""}]  # ineligible ones not


def test_both_texts_are_quoted_when_the_carrier_has_a_description() -> None:
    jev = FakeJev(blocks={"S-Logistics": 0.91})
    carriers = replace_carrier(with_note(S_LOGISTICS, "Dry cargo in Florida.", NoteStatus.NONE))

    quote = service(jev, carriers).quote(miami_orlando("Soğuk zincir şart."))

    s = next(r for r in quote.rejected if r.carrier_name == "S-Logistics")
    assert s.reasons == (
        'Açıklamalar uyumsuz: sipariş "Soğuk zincir şart.", firma "Dry cargo in Florida." (Jev, olasılık 0.91)',
    )


def test_unrelated_order_description_keeps_the_cheapest_carrier() -> None:
    jev = FakeJev(blocks={"S-Logistics": 0.04, "M-Logistics": 0.02})

    quote = service(jev).quote(miami_orlando("ofis sandalyeleri"))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.SELECTED, "S-Logistics")
    assert quote.rejected and all("uyumsuz" not in " ".join(r.reasons) for r in quote.rejected)


def test_uncertain_match_on_the_winner_needs_review() -> None:
    jev = FakeJev(blocks={"S-Logistics": 0.50})

    quote = service(jev).quote(miami_orlando("mümkünse S-Logistics olmasın"))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.NEEDS_REVIEW, "S-Logistics")
    assert any(
        "S-Logistics ile sipariş açıklamasının uyumu belirsiz (uyumsuzluk olasılığı 0.50)" in w for w in quote.warnings
    )


def test_excluding_every_carrier_reports_no_carrier() -> None:
    jev = FakeJev(blocks={"S-Logistics": 0.96, "M-Logistics": 0.96})

    quote = service(jev).quote(miami_orlando("S-Logistics ve M-Logistics ile çalışmıyoruz"))

    assert quote.status is QuoteStatus.NO_CARRIER
    assert "Uygun firma yok." in quote.explanation


def test_order_description_is_never_silently_ignored_without_jev() -> None:
    quote = service(None).quote(miami_orlando(DONT_USE_S))

    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert any("Sipariş açıklaması ve firma notları kontrol edilemedi" in w for w in quote.warnings)


def test_order_description_with_jev_outage_needs_review() -> None:
    quote = service(FakeJev(fail=True)).quote(miami_orlando(DONT_USE_S))

    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert any(
        "sipariş açıklaması ve firma notları kontrol edilmedi: M-Logistics, S-Logistics" in w for w in quote.warnings
    )


# --- a carrier requested in the order description -------------------------------------------


def test_requested_carrier_is_selected_over_a_cheaper_one() -> None:
    jev = FakeJev(requested=choice("M-Logistics", 0.95))

    quote = service(jev).quote(miami_orlando("M-Logistics ile çalışmak istiyorum"))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.SELECTED, "M-Logistics")
    assert quote.requested == "M-Logistics"
    assert (
        "Belirleyici kriter: sipariş açıklamasında istenen firma — M-Logistics: istendi, S-Logistics: istenmedi."
        in quote.explanation
    )


def test_ineligible_requested_carrier_is_explained_and_the_next_one_is_selected() -> None:
    jev = FakeJev(requested=choice("A-Logistics", 0.95))

    quote = service(jev).quote(miami_orlando("A-Logistics ile çalışmak istiyorum"))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.SELECTED, "S-Logistics")
    assert jev.requestable == [["A-Logistics", "B-Logistics", "M-Logistics", "S-Logistics"]]  # all, not only eligible
    assert jev.notes_asked == [{"S-Logistics": "", "M-Logistics": ""}]  # only eligible ones are compared
    assert (
        "Sipariş açıklamasında A-Logistics istendi ancak uygun değil (Mesafe 235 mil, üst sınır 200 mil; "
        "40 ft konteyner taşımıyor (taşıdığı: 45 ft)); sıradaki uygun firma seçildi. S-Logistics seçildi"
    ) in quote.explanation
    assert "Elenenler: B-Logistics (" in quote.explanation  # A's reasons are not repeated


def test_requested_carrier_ruled_out_by_its_own_note_falls_back_with_the_reason() -> None:
    jev = FakeJev(requested=choice("B-Logistics", 0.93), blocks={"B-Logistics": 0.95})
    carriers = replace_carrier(with_note(B_LOGISTICS, "No Atlanta deliveries until December."))

    quote = service(jev, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer", description="B olsun"))

    assert quote.selected is not None and quote.selected.carrier.name == "M-Logistics"
    assert "Sipariş açıklamasında B-Logistics istendi ancak uygun değil (Açıklamalar uyumsuz" in quote.explanation


def test_requested_carrier_with_medium_confidence_is_used_but_needs_review() -> None:
    jev = FakeJev(requested=choice("M-Logistics", 0.70))

    quote = service(jev).quote(miami_orlando("M ile mi çalışsak?"))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.NEEDS_REVIEW, "M-Logistics")
    assert any("İstenen firma Jev ile düşük güvenle belirlendi (M-Logistics, güven 0.70)" in w for w in quote.warnings)


def test_requested_carrier_with_low_confidence_is_not_guessed() -> None:
    jev = FakeJev(requested=choice("M-Logistics", 0.40))

    quote = service(jev).quote(miami_orlando("belki M"))

    assert (quote.status, quote.selected and quote.selected.carrier.name) == (QuoteStatus.SELECTED, "S-Logistics")
    assert quote.requested is None
    assert any("istenen firma belirlenemedi" in w for w in quote.warnings)


def test_requested_carrier_comes_first_whatever_the_rules_order_the_others() -> None:
    jev = FakeJev(requested=choice("M-Logistics", 0.95))
    rules = default_rules(ranking=["hq_proximity", "total_cost"])
    quote_service = QuoteService(InMemoryCarrierRepository(CASE_CARRIERS), offline_distances(), StaticRules(rules), jev)

    quote = quote_service.quote(miami_orlando("M-Logistics ile çalışmak istiyorum"))

    assert [c.carrier.name for c in quote.ranking] == ["M-Logistics", "S-Logistics"]  # then the rules
    assert "Belirleyici kriter: sipariş açıklamasında istenen firma" in quote.explanation


def test_structured_order_without_description_never_asks_for_a_requested_carrier() -> None:
    jev = FakeJev()
    carriers = replace_carrier(with_note(B_LOGISTICS, "Limited reefer capacity."))

    service(jev, carriers).quote(miami_atlanta(container_size=20, cargo_type="Reefer"))

    assert jev.requestable == [[]]
