"""Container sizes an order may use: the standard sizes in rules.yaml plus every size a carrier carries.

Carriers are not limited to the standard sizes; a size one of them adds (53 ft) becomes selectable on
orders at once. One function feeds the quote form, order validation, the text parser and Jev's choices.
"""

from collections.abc import Iterable

from app.models.carrier import Carrier
from app.selection.rules import RuleSet

MAX_CONTAINER_FT = 99  # the free-text parser reads two-digit sizes


def container_sizes(rules: RuleSet, carriers: Iterable[Carrier]) -> tuple[int, ...]:
    sizes = set(rules.container_sizes)
    for carrier in carriers:
        sizes |= carrier.container_sizes
    return tuple(sorted(sizes))
