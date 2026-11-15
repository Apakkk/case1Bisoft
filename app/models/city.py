"""Cities offered as suggestions: the shipped catalog plus cities found through the routing service."""

from dataclasses import dataclass
from enum import StrEnum


class CitySource(StrEnum):
    CATALOG = "catalog"  # shipped: config/cities.csv + city_aliases.yaml, and config/us_cities.csv
    ORS = "ors"  # found by OpenRouteService, stored in the cities table


@dataclass(frozen=True, slots=True)
class City:
    """A city (never a district, street or venue) with its US state code and coordinates."""

    name: str
    state: str
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Place:
    """A city as shown to people: name and US state code ('Tampa', 'FL' -> 'Tampa, FL')."""

    name: str
    state: str = ""

    @property
    def label(self) -> str:
        return f"{self.name}, {self.state}" if self.state else self.name


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
