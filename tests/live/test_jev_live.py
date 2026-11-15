"""Opt-in checks against the real Jev API (make test-live). Two requests in total, kept tiny on purpose."""

import pytest

from app.clients.jev_client import JevClient
from app.config import get_settings
from app.dependencies import build_jev_client
from app.models.order import Order

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def jev() -> JevClient:
    client = build_jev_client(get_settings())
    if client is None:
        pytest.skip("TYPESAFE_API_KEY is not set")
    return client


def test_free_text_cargo_is_classified(jev: JevClient) -> None:
    result = jev.classify_order("frozen shrimp", ["Dry", "Reefer", "Hazardous"], None)

    assert result.cargo_type is not None
    assert result.cargo_type.choice == "Reefer"


def test_restrictive_note_blocks_and_neutral_note_allows(jev: JevClient) -> None:
    notes = {"M-Logistics": "Şu an tehlikeli yük kabul etmiyoruz.", "X-Logistics": "Nationwide network, 24/7 dispatch."}

    result = jev.notes_block_order(Order("Tampa", "Orlando", 20, "Hazardous"), notes)

    assert result.block_probability["M-Logistics"] >= 0.85
    assert result.block_probability["X-Logistics"] <= 0.15
