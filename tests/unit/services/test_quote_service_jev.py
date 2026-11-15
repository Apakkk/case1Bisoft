"""Where Jev enters the quote flow, and what happens when it is unsure or unavailable (FakeJev only)."""

from dataclasses import replace

from app.models.carrier import Carrier, NoteStatus
from app.models.quote import QuoteStatus
from app.schemas.quote import QuoteRequest
from app.services.quote_service import QuoteService
from tests.case_data import B_LOGISTICS, CASE_CARRIERS, M_LOGISTICS, default_rules
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


def test_structured_orders_never_call_jev() -> None:
    jev = FakeJev()

    service(jev).quote(miami_atlanta(container_size=20, cargo_type="Reefer", cargo_description="frozen shrimp"))

    assert jev.calls == []


def test_confident_classification_is_used() -> None:
    jev = FakeJev(cargo=choice("Reefer", 0.95, Dry=0.04, Reefer=0.95, Hazardous=0.01))

    quote = service(jev).quote(miami_atlanta(container_size=20, cargo_description="frozen shrimp"))

    assert quote.status is QuoteStatus.SELECTED
    assert quote.order.cargo_type == "Reefer"
    assert quote.order.inferred == {"cargo_type": "jev"}
    assert quote.selected is not None and quote.selected.carrier.name == "B-Logistics"
    assert [(c.step, c.answer, c.confidence) for c in quote.jev_calls] == [("cargo_type", "Reefer", 0.95)]


def test_medium_confidence_computes_but_needs_review() -> None:
    jev = FakeJev(cargo=choice("Reefer", 0.72, Dry=0.25, Reefer=0.72, Hazardous=0.03))

    quote = service(jev).quote(miami_atlanta(container_size=20, cargo_description="seafood"))

    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert quote.selected is not None
    assert any("Yük tipi Jev ile düşük güvenle belirlendi (Reefer, güven 0.72)" in w for w in quote.warnings)


def test_low_confidence_is_never_guessed() -> None:
    jev = FakeJev(cargo=choice("Dry", 0.41, Dry=0.45, Reefer=0.40, Hazardous=0.15))

    quote = service(jev).quote(miami_atlanta(container_size=20, cargo_description="mixed goods"))

    assert quote.status is QuoteStatus.NEEDS_INPUT
    assert quote.selected is None
    assert "yük tipi belirlenemedi" in quote.explanation
    assert any("tahmin edilmedi" in w for w in quote.warnings)


def test_possible_hazardous_cargo_triggers_review_even_when_another_label_wins() -> None:
    jev = FakeJev(cargo=choice("Dry", 0.90, Dry=0.78, Reefer=0.02, Hazardous=0.20))

    quote = service(jev).quote(miami_atlanta(container_size=20, cargo_description="cleaning supplies"))

    assert quote.status is QuoteStatus.NEEDS_REVIEW
    assert any("Tehlikeli yük olasılığı 0.20" in w for w in quote.warnings)


def test_size_and_cargo_are_asked_in_a_single_request() -> None:
    jev = FakeJev(size=choice("40", 0.93), cargo=choice("Dry", 0.97))

    quote = service(jev).quote(QuoteRequest(origin="Miami", destination="Orlando", cargo_description="office chairs"))

    assert jev.calls == ["classify_order"]
    assert quote.order.inferred == {"container_size": "jev", "cargo_type": "jev"}
    assert quote.selected is not None and quote.selected.carrier.name == "S-Logistics"


def test_jev_outage_asks_for_input_instead_of_failing() -> None:
    quote = service(FakeJev(fail=True)).quote(miami_atlanta(container_size=20, cargo_description="frozen shrimp"))

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

    assert jev.calls == ["notes_block_order"]
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
