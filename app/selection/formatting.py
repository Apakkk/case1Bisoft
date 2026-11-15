"""Number formatting shared by constraint reasons and explanations."""

from collections.abc import Iterable
from decimal import Decimal


def fmt_money(value: Decimal) -> str:
    return f"${value:,.2f}"


def fmt_rate(value: Decimal) -> str:
    """At least two decimals, more only when the rate has them: $1.00, $0.40, $0.375."""
    exponent = value.normalize().as_tuple().exponent
    decimals = max(2, -exponent) if isinstance(exponent, int) else 2
    return f"${value:,.{decimals}f}"


def fmt_miles(value: Decimal) -> str:
    """Whole miles without decimals (660), otherwise one decimal (234.7)."""
    if value == value.to_integral_value():
        return f"{int(value)}"
    return f"{value:.1f}"


def fmt_list[T: (int, str)](values: Iterable[T]) -> str:
    return ", ".join(str(v) for v in sorted(values))
