from decimal import Decimal

import pytest

from app.repositories.distance_cache_repository import PostgresDistanceCache

pytestmark = pytest.mark.db


def test_cache_is_symmetric_and_upserts(distance_cache: PostgresDistanceCache) -> None:
    assert distance_cache.get("Testville A", "Testville B") is None

    distance_cache.put("Testville A", "Testville B", Decimal("281.4"), "ors")
    assert distance_cache.get("Testville B", "Testville A") == Decimal("281.4")

    distance_cache.put("Testville B", "Testville A", Decimal("280.0"), "ors")
    assert distance_cache.get("Testville A", "Testville B") == Decimal("280.0")
