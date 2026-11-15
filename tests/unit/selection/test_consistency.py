"""Does the order's description contradict a field the user entered? (pure decision, no Jev)"""

import pytest

from app.selection.consistency import Mismatch, cargo_mismatch, confirmation_question, size_mismatch
from tests.case_data import default_rules

BANDS = default_rules().confidence  # auto_accept 0.85, needs_review 0.60
HAZMAT = Mismatch("cargo_type", "Dry", "Hazardous", 0.93, "jev")
BIGGER = Mismatch("container_size", "20 ft", "40 ft", None, "text")


@pytest.mark.parametrize(
    ("described", "confidence"),
    [
        ("Dry", 0.99),  # the text agrees with the form
        (None, 0.95),  # the text names no cargo (Jev: not_stated)
        ("Hazardous", 0.59),  # too unsure to have filled an empty field either
    ],
)
def test_no_mismatch(described: str | None, confidence: float) -> None:
    assert cargo_mismatch("Dry", described, confidence, BANDS) is None


def test_another_cargo_type_read_as_surely_as_a_filled_field_is_a_mismatch() -> None:
    assert cargo_mismatch("Dry", "Hazardous", 0.60, BANDS) == Mismatch("cargo_type", "Dry", "Hazardous", 0.60, "jev")


def test_a_different_size_stated_in_the_text_is_a_mismatch() -> None:
    assert size_mismatch(20, 40) == BIGGER


@pytest.mark.parametrize("parsed", [None, 20])
def test_no_size_in_the_text_or_the_same_size_is_no_mismatch(parsed: int | None) -> None:
    assert size_mismatch(20, parsed) is None


def test_the_question_names_every_contradicted_field() -> None:
    assert confirmation_question((HAZMAT,)) == (
        "Girilen yük tipi ile açıklama uyumsuz. Bu şekilde devam etmek istiyor musunuz?"
    )
    assert confirmation_question((BIGGER, HAZMAT)).startswith("Girilen konteyner ölçüsü ve yük tipi ile açıklama")


def test_the_detail_says_where_the_other_value_came_from() -> None:
    assert HAZMAT.detail() == "girilen Dry, açıklamaya göre Hazardous (Jev, güven 0.93)"
    assert BIGGER.detail() == "girilen 20 ft, açıklamaya göre 40 ft (açıklamadaki ölçü)"
