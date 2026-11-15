"""PostgreSQL-backed distance cache: each off-table route hits the routing API only once."""

from decimal import Decimal

from app.repositories.carrier_repository import ConnectionFactory


class PostgresDistanceCache:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def get(self, a: str, b: str) -> Decimal | None:
        first, second = sorted((a, b))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT miles FROM distance_cache WHERE city_a = %s AND city_b = %s", (first, second)
            ).fetchone()
        return Decimal(row["miles"]) if row else None

    def put(self, a: str, b: str, miles: Decimal, source: str) -> None:
        first, second = sorted((a, b))
        with self._connect() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO distance_cache (city_a, city_b, miles, source) VALUES (%s, %s, %s, %s)
                ON CONFLICT (city_a, city_b)
                DO UPDATE SET miles = EXCLUDED.miles, source = EXCLUDED.source, created_at = now()
                """,
                (first, second, miles, source),
            )
