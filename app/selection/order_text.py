"""Deterministic extraction from free-text orders, tried before asking Jev.

A size only counts with a unit ("40 ft", "40'lık", "40HC"), so "20 tons" is never read as 20 ft.
A container count ("3 adet") is only detected, so the quote can say it priced one container.
"""

import re
from collections.abc import Collection

# Two digits that are not part of a longer number; "2x40HC" counts (a letter may come before).
_NUMBER = r"(?<![\d.,])(\d{2})"

_SIZE_PATTERNS = (
    re.compile(rf"{_NUMBER}\s*-?\s*(?:ft|feet|foot|footer)\b", re.IGNORECASE),
    # 40'lık, or 40' as the foot mark; not a Turkish case ending on a date ("ayın 20'sinde").
    re.compile(rf"{_NUMBER}\s*['’′](?:lik|lık|luk|lük|(?![a-zçğıöşü]))", re.IGNORECASE),
    re.compile(rf"{_NUMBER}\s*(?:hc|dc|dv|gp)\b", re.IGNORECASE),
    re.compile(rf"{_NUMBER}(?:lik|lık|luk|lük)\b", re.IGNORECASE),
)


def parse_container_size(text: str, allowed: Collection[int]) -> int | None:
    """The single catalog size mentioned with a unit; None when absent or ambiguous."""
    found = {int(m.group(1)) for pattern in _SIZE_PATTERNS for m in pattern.finditer(text)}
    sizes = found & set(allowed)
    return sizes.pop() if len(sizes) == 1 else None


# A quote is for one container. A count only counts with a container word or as "2x40", so "40 ton" is
# not a count. Spelled-out counts stop at nine: "on" (ten) is also an English word.
_WORD_COUNTS = {
    **dict.fromkeys(("iki", "two"), 2),
    **dict.fromkeys(("üç", "three"), 3),
    **dict.fromkeys(("dört", "four"), 4),
    **dict.fromkeys(("beş", "five"), 5),
    **dict.fromkeys(("altı", "six"), 6),
    **dict.fromkeys(("yedi", "seven"), 7),
    **dict.fromkeys(("sekiz", "eight"), 8),
    **dict.fromkeys(("dokuz", "nine"), 9),
}
_COUNT = rf"(?<![\w.,])(\d{{1,3}}|{'|'.join(_WORD_COUNTS)})"

_COUNT_PATTERNS = (
    re.compile(rf"{_COUNT}\s*[x×]\s*\d{{2}}(?!\d)", re.IGNORECASE),  # 2x40HC
    re.compile(rf"{_COUNT}\s*(?:adet|tane|konteyner\w*|containers?)\b", re.IGNORECASE),  # 3 adet, two containers
)


def several_containers(text: str) -> list[str]:
    """The count phrases ("3 adet", "2x40") when together they state more than one container; else []."""
    found: list[re.Match[str]] = []
    for m in sorted((m for p in _COUNT_PATTERNS for m in p.finditer(text)), key=lambda m: m.start()):
        if not found or m.start() >= found[-1].end():  # "2 x 40 konteyner" is one count, not two
            found.append(m)
    if sum(_count(m.group(1)) for m in found) <= 1:
        return []
    return [m.group(0) for m in found]


def _count(token: str) -> int:
    if token.isdigit():
        return int(token)
    return _WORD_COUNTS[token.casefold().replace("̇", "")]  # "İki".casefold() keeps a combining dot
