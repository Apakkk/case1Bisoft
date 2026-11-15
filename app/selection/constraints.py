"""Hard constraints. Each returns a Turkish reason when the carrier fails, otherwise None.

Adding a constraint = one function + one registry entry + its name in rules.yaml `filters`.
"""

from collections.abc import Callable
from decimal import Decimal

from app.models.carrier import Carrier
from app.models.order import Order
from app.selection.formatting import fmt_list, fmt_miles

Constraint = Callable[[Carrier, Order, Decimal], str | None]


def distance_range(carrier: Carrier, order: Order, miles: Decimal) -> str | None:
    if carrier.min_miles is not None and miles < carrier.min_miles:
        return f"Mesafe {fmt_miles(miles)} mil, alt sınır {fmt_miles(carrier.min_miles)} mil"
    if carrier.max_miles is not None and miles > carrier.max_miles:
        return f"Mesafe {fmt_miles(miles)} mil, üst sınır {fmt_miles(carrier.max_miles)} mil"
    return None


def container_size(carrier: Carrier, order: Order, miles: Decimal) -> str | None:
    if order.container_size in carrier.container_sizes:
        return None
    return f"{order.container_size} ft konteyner taşımıyor (taşıdığı: {fmt_list(carrier.container_sizes)} ft)"


def cargo_type(carrier: Carrier, order: Order, miles: Decimal) -> str | None:
    if order.cargo_type in carrier.cargo_types:
        return None
    return f"{order.cargo_type} yük taşımıyor (taşıdığı: {fmt_list(carrier.cargo_types)})"


CONSTRAINTS: dict[str, Constraint] = {
    "distance_range": distance_range,
    "container_size": container_size,
    "cargo_type": cargo_type,
}
