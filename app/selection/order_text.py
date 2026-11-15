"""Deterministic extraction from free-text orders, tried before asking Jev.

A size only counts with a unit ("40 ft", "40'lık", "40HC"), so "20 tons" is never read as 20 ft.
"""

import re
from collections.abc import Collection

_SIZE_PATTERNS = (
    re.compile(r"\b(\d{2})\s*-?\s*(?:ft|feet|foot|footer)\b", re.IGNORECASE),
    re.compile(r"\b(\d{2})\s*['’′](?:lik|lık|luk|lük)?", re.IGNORECASE),
    re.compile(r"\b(\d{2})\s*(?:hc|dc|dv|gp)\b", re.IGNORECASE),
    re.compile(r"\b(\d{2})(?:lik|lık|luk|lük)\b", re.IGNORECASE),
)


def parse_container_size(text: str, allowed: Collection[int]) -> int | None:
    """The single catalog size mentioned with a unit; None when absent or ambiguous."""
    found = {int(m.group(1)) for pattern in _SIZE_PATTERNS for m in pattern.finditer(text)}
    sizes = found & set(allowed)
    return sizes.pop() if len(sizes) == 1 else None
