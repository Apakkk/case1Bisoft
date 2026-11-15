"""PostgreSQL connection pool lifecycle."""

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

Pool = ConnectionPool[Connection[DictRow]]


def create_pool(database_url: str) -> Pool:
    """Open a pool in the background so the app starts even if the database is still booting."""
    pool: Pool = ConnectionPool(
        database_url,
        connection_class=Connection[DictRow],
        kwargs={"row_factory": dict_row},
        min_size=1,
        max_size=5,
        timeout=5,
        open=False,
    )
    pool.open(wait=False)
    return pool
