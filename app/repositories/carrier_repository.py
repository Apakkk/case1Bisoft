"""Carrier persistence: a Protocol for the service layer and a PostgreSQL implementation (parametrized SQL)."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any, Protocol

from psycopg import Connection, errors
from psycopg.rows import DictRow

from app.models.carrier import Carrier, NoteStatus

ConnectionFactory = Callable[[], AbstractContextManager[Connection[DictRow]]]


class CarrierRepositoryError(Exception):
    pass


class DuplicateCarrierError(CarrierRepositoryError):
    def __init__(self, name: str) -> None:
        super().__init__(f"a carrier named '{name}' already exists")
        self.name = name


class InvalidCarrierError(CarrierRepositoryError):
    """A database CHECK constraint rejected the row (the service validates first; this is the safety net)."""

    def __init__(self, constraint: str | None) -> None:
        super().__init__(f"carrier violates constraint {constraint}")
        self.constraint = constraint


class CarrierRepository(Protocol):
    def list(self) -> list[Carrier]: ...
    def get(self, carrier_id: int) -> Carrier | None: ...
    def create(self, carrier: Carrier) -> Carrier: ...
    def update(self, carrier_id: int, carrier: Carrier) -> Carrier | None: ...
    def delete(self, carrier_id: int) -> bool: ...


_COLUMNS = (
    "id, name, hq_city, min_miles, max_miles, container_sizes, cargo_types, rate_per_mile, "
    "description, note_status, note_confidence"
)
_VALUES = (
    "%(name)s, %(hq_city)s, %(min_miles)s, %(max_miles)s, %(container_sizes)s::smallint[], "
    "%(cargo_types)s::text[], %(rate_per_mile)s, %(description)s, %(note_status)s, %(note_confidence)s"
)


class PostgresCarrierRepository:
    def __init__(self, connect: ConnectionFactory) -> None:
        self._connect = connect

    def list(self) -> list[Carrier]:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM carriers ORDER BY lower(name)").fetchall()
        return [_to_carrier(row) for row in rows]

    def get(self, carrier_id: int) -> Carrier | None:
        with self._connect() as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM carriers WHERE id = %s", (carrier_id,)).fetchone()
        return _to_carrier(row) if row else None

    def create(self, carrier: Carrier) -> Carrier:
        sql = f"""
            INSERT INTO carriers (name, hq_city, min_miles, max_miles, container_sizes, cargo_types,
                                  rate_per_mile, description, note_status, note_confidence)
            VALUES ({_VALUES})
            RETURNING {_COLUMNS}
        """
        row = self._write(sql, _params(carrier), carrier.name)
        assert row is not None
        return _to_carrier(row)

    def update(self, carrier_id: int, carrier: Carrier) -> Carrier | None:
        sql = f"""
            UPDATE carriers
               SET (name, hq_city, min_miles, max_miles, container_sizes, cargo_types,
                    rate_per_mile, description, note_status, note_confidence) = ({_VALUES}),
                   updated_at = now()
             WHERE id = %(id)s
            RETURNING {_COLUMNS}
        """
        row = self._write(sql, {**_params(carrier), "id": carrier_id}, carrier.name)
        return _to_carrier(row) if row else None

    def delete(self, carrier_id: int) -> bool:
        with self._connect() as conn, conn.transaction():
            return conn.execute("DELETE FROM carriers WHERE id = %s", (carrier_id,)).rowcount == 1

    def _write(self, sql: str, params: dict[str, Any], name: str) -> DictRow | None:
        try:
            with self._connect() as conn, conn.transaction():  # savepoint when nested (tests)
                return conn.execute(sql, params).fetchone()
        except errors.UniqueViolation as error:
            raise DuplicateCarrierError(name) from error
        except errors.CheckViolation as error:
            raise InvalidCarrierError(error.diag.constraint_name) from error


def _params(carrier: Carrier) -> dict[str, Any]:
    return {
        "name": carrier.name,
        "hq_city": carrier.hq_city,
        "min_miles": carrier.min_miles,
        "max_miles": carrier.max_miles,
        "container_sizes": sorted(carrier.container_sizes),
        "cargo_types": sorted(carrier.cargo_types),
        "rate_per_mile": carrier.rate_per_mile,
        "description": carrier.description,
        "note_status": carrier.note_status.value,
        "note_confidence": carrier.note_confidence,
    }


def _to_carrier(row: DictRow) -> Carrier:
    confidence = row["note_confidence"]
    return Carrier(
        id=row["id"],
        name=row["name"],
        hq_city=row["hq_city"],
        min_miles=row["min_miles"],
        max_miles=row["max_miles"],
        container_sizes=frozenset(row["container_sizes"]),
        cargo_types=frozenset(row["cargo_types"]),
        rate_per_mile=Decimal(row["rate_per_mile"]),
        description=row["description"],
        note_status=NoteStatus(row["note_status"]),
        note_confidence=float(confidence) if confidence is not None else None,
    )
