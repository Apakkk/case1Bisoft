"""Integration fixtures: one real PostgreSQL connection per test, rolled back afterwards."""

from collections.abc import Iterator
from contextlib import nullcontext

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from app.config import get_settings
from app.repositories.carrier_repository import PostgresCarrierRepository
from app.repositories.city_repository import PostgresCityRepository
from app.repositories.distance_cache_repository import PostgresDistanceCache


@pytest.fixture
def conn() -> Iterator[Connection[DictRow]]:
    connection = psycopg.connect(get_settings().database_url, row_factory=dict_row)
    try:
        # Outer transaction that is always rolled back: the repository's own transaction()
        # blocks become savepoints inside it, so nothing a test writes is ever committed.
        with connection.transaction(force_rollback=True):
            yield connection
    finally:
        connection.close()


@pytest.fixture
def carriers(conn: Connection[DictRow]) -> PostgresCarrierRepository:
    return PostgresCarrierRepository(lambda: nullcontext(conn))


@pytest.fixture
def distance_cache(conn: Connection[DictRow]) -> PostgresDistanceCache:
    return PostgresDistanceCache(lambda: nullcontext(conn))


@pytest.fixture
def cities(conn: Connection[DictRow]) -> PostgresCityRepository:
    return PostgresCityRepository(lambda: nullcontext(conn))
