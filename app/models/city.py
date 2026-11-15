"""Cities offered as suggestions: the shipped catalog plus cities found through the routing service."""

from dataclasses import dataclass
from enum import StrEnum


class CitySource(StrEnum):
    CATALOG = "catalog"  # config/cities.csv and config/city_aliases.yaml
    ORS = "ors"  # found by OpenRouteService autocomplete, stored in the cities table


@dataclass(frozen=True, slots=True)
class City:
    """A city (never a district, street or venue) with its US state code and coordinates."""

    name: str
    state: str
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class CitySuggestion:
    name: str
    state: str
    source: CitySource
    match: tuple[int, int] | None = None  # span of `name` that matched the query, for highlighting

    @property
    def parts(self) -> tuple[str, str, str]:
        """(before, matched, after) so a template can bold the matched letters."""
        if self.match is None:
            return (self.name, "", "")
        start, end = self.match
        return (self.name[:start], self.name[start:end], self.name[end:])


@dataclass(frozen=True, slots=True)
class CitySuggestions:
    items: list[CitySuggestion]
    warnings: tuple[str, ...] = ()  # Turkish notes for the user, e.g. the map service was unreachable
