"""Cities learned from the routing service (table `cities`, db/migrations/001_cities.sql)."""

from collections.abc import Sequence
from typing import Protocol

from psycopg.rows import DictRow

from app.clients.distance.cities import city_key
from app.models.city import City
from app.repositories.carrier_repository import ConnectionFactory

# SQL twin of city_key(): lower case, dots and runs of spaces become one space.
_KEY = "btrim(regexp_replace(lower(name), '[.[:space:]]+', ' ', 'g'))"


class CityRepository(Protocol):
    def search(self, query_key: str, limit: int = 50) -> list[City]: ...
    def find(self, name: str) -> City | None: ...
    def add(self, cities: Sequence[City]) -> None: ...


class PostgresCityRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def search(self, query_key: str, limit: int = 50) -> list[City]:
        """Cities whose name, or a later word in it, starts with `query_key` (a city_key).

        Insertion order within each group: rows were added in ORS relevance order.
        """
        like = _escape_like(query_key)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT name, state, lat, lon FROM cities
                WHERE {_KEY} LIKE %(prefix)s OR {_KEY} LIKE %(word)s OR {_KEY} LIKE %(hyphen)s
                ORDER BY {_KEY} LIKE %(prefix)s DESC, id
                LIMIT %(limit)s
                """,
                {"prefix": f"{like}%", "word": f"% {like}%", "hyphen": f"%-{like}%", "limit": limit},
            ).fetchall()
        return [_city(row) for row in rows]

    def find(self, name: str) -> City | None:
        """Case-insensitive exact match: 'mcallen' finds 'McAllen'."""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT name, state, lat, lon FROM cities WHERE {_KEY} = %s LIMIT 1", (city_key(name),)
            ).fetchone()
        return _city(row) if row else None

    def add(self, cities: Sequence[City]) -> None:
        """Insert new cities; a name that is already stored keeps its first row."""
        if not cities:
            return
        with self._connect() as conn, conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO cities (name, state, lat, lon) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [(c.name, c.state, c.lat, c.lon) for c in cities],
            )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _city(row: DictRow) -> City:
    return City(name=row["name"], state=row["state"], lat=float(row["lat"]), lon=float(row["lon"]))
