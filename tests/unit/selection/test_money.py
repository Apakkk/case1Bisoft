from decimal import Decimal

import pytest

from app.selection.money import total_cost

D = Decimal


@pytest.mark.parametrize(
    ("rate", "miles", "expected"),
    [
        ("0.40", "235", "94.00"),  # order 2
        ("2.00", "140", "280.00"),  # order 4
        ("0.40", "234.7", "93.88"),  # fractional miles from a routing API
        ("0.125", "1", "0.13"),  # ROUND_HALF_UP, not banker's rounding
        ("0.1", "3", "0.30"),  # 0.1 * 3 is exactly 0.30 with Decimal (not 0.30000000000000004)
    ],
)
def test_total_cost_is_exact_and_rounded_to_cents(rate: str, miles: str, expected: str) -> None:
    result = total_cost(D(rate), D(miles))

    assert result == D(expected)
    assert result.as_tuple().exponent == -2
