from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def total_cost(rate_per_mile: Decimal, miles: Decimal) -> Decimal:
    """Exact Decimal arithmetic, rounded half-up to cents (never float)."""
    return (rate_per_mile * miles).quantize(CENT, rounding=ROUND_HALF_UP)
