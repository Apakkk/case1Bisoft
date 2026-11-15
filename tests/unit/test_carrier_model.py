"""Carrier.note_may_restrict: the one rule for whether a description is sent to Jev with an order."""

from dataclasses import replace

import pytest

from app.models.carrier import NoteStatus
from tests.case_data import M_LOGISTICS


@pytest.mark.parametrize(
    ("description", "status", "confidence", "auto_accept", "expected"),
    [
        ("", NoteStatus.CONSTRAINT, 0.95, 0.85, False),  # no text, nothing to check
        ("Nationwide.", NoteStatus.NONE, None, 0.85, False),  # seeded as harmless
        ("Hafta sonu yok.", NoteStatus.UNCHECKED, None, 0.85, True),  # Jev was down when it was saved
        ("Hafta sonu yok.", NoteStatus.CONSTRAINT, 0.93, 0.85, True),
        ("Genelde hafta içi.", NoteStatus.NONE, 0.12, 0.85, False),  # 0.12 <= 0.15
        ("Genelde hafta içi.", NoteStatus.NONE, 0.12, 0.90, True),  # 0.12 > 0.10: stricter threshold
        ("Genelde hafta içi.", NoteStatus.CONSTRAINT, 0.18, 0.80, False),  # 0.18 <= 0.20: looser threshold
    ],
)
def test_the_saved_probability_is_judged_against_todays_threshold(
    description: str, status: NoteStatus, confidence: float | None, auto_accept: float, expected: bool
) -> None:
    carrier = replace(M_LOGISTICS, description=description, note_status=status, note_confidence=confidence)

    assert carrier.note_may_restrict(auto_accept) is expected
