from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Order:
    """A normalized order: canonical city names and catalog values (e.g. "Reefer", 40)."""

    origin: str
    destination: str
    container_size: int
    cargo_type: str
