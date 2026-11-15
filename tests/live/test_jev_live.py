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


def test_order_and_carrier_descriptions_are_matched(jev: JevClient) -> None:
    carriers = {
        "S-Logistics": "Tampa-based short-haul specialist for dry cargo in Florida.",  # excluded by the order note
        "M-Logistics": "Şu an Orlando'ya teslimat yapmıyoruz.",  # its own note rules the order out
        "X-Logistics": "Nationwide network, 24/7 dispatch.",  # no conflict
    }

    result = jev.check_compatibility(
        Order("Miami", "Orlando", 40, "Dry"), "S-Logistics ile çalışmak istemiyorum.", carriers
    )

    assert result.conflict_probability["S-Logistics"] >= 0.85
    assert result.conflict_probability["M-Logistics"] >= 0.85
    assert result.conflict_probability["X-Logistics"] <= 0.15
