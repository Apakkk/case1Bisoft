"""City names: normalization, known coordinates (config/cities.csv + config/city_aliases.yaml) and suggestions."""

import csv
import re
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.models.city import City, CitySource, CitySuggestion

_STATE_SUFFIX = re.compile(r",\s*[A-Za-z]{2}$")
_WORD_START = re.compile(r"[ \-]")

Coordinates = tuple[float, float]  # (lat, lon)


def city_key(name: str) -> str:
    """Comparison key: case, dots and extra spaces do not matter ('ST. louis ' == 'St. Louis').

    Turkish 'İ'/'ı' count as 'i' ('MİAMİ' typed with Caps Lock on a Turkish keyboard is Miami).
    """
    return " ".join(name.replace(".", " ").replace("İ", "i").replace("ı", "i").split()).casefold()


@dataclass(frozen=True, slots=True)
class CityEntry:
    """Something a query can match: a city name, or an alias that stands for one."""

    key: str  # city_key of the matched text
    name: str  # the city that is suggested
    state: str
    source: CitySource
    is_alias: bool = False
    rank: int = 0  # cities found online: the routing service's relevance order (catalog: 0, alphabetical)

    @classmethod
    def of(cls, city: City, source: CitySource, rank: int = 0) -> "CityEntry":
        return cls(city_key(city.name), city.name, city.state, source, rank=rank)


@dataclass(frozen=True, slots=True)
class CityDirectory:
    canonical: Mapping[str, str]  # lookup key -> canonical name (known cities and aliases)
    coordinates: Mapping[str, Coordinates]  # canonical name -> (lat, lon)
    states: Mapping[str, str] = field(default_factory=dict)  # canonical name -> state code

    def lookup(self, raw: str) -> str | None:
        """Canonical name of a catalog city or alias, or None if the catalog does not know it."""
        return self.canonical.get(city_key(_STATE_SUFFIX.sub("", raw.strip())))

    def normalize(self, raw: str) -> str:
        """'ft. lauderdale' -> 'Fort Lauderdale', 'Miami, FL' -> 'Miami'; unknown names are title-cased."""
        known = self.lookup(raw)
        if known is not None:
            return known
        cleaned = _STATE_SUFFIX.sub("", raw.strip())
        return string.capwords(" ".join(cleaned.split()))

    def coordinates_of(self, city: str) -> Coordinates | None:
        return self.coordinates.get(city)

    def entries(self) -> list[CityEntry]:
        return [
            CityEntry(key, name, self.states.get(name, ""), CitySource.CATALOG, is_alias=key != city_key(name))
            for key, name in self.canonical.items()
        ]


def match_tier(key: str, query_key: str) -> int | None:
    """0 = the name starts with the query, 1 = a later word does ('lau' in 'Fort Lauderdale'), None = no match.

    Letters in the middle of a word do not count: 'o' suggests Orlando, not Boston.
    """
    if key.startswith(query_key):
        return 0
    if any(key.startswith(query_key, gap.end()) for gap in _WORD_START.finditer(key)):
        return 1
    return None


def rank_suggestions(query: str, entries: Iterable[CityEntry], limit: int = 5) -> list[CitySuggestion]:
    """Best `limit` cities for what the user typed so far.

    Order: name starts with the query -> a later word does; catalog cities (alphabetical) before ones found
    online (in the routing service's relevance order, so 'boca' lists Boca Raton first). Each city appears
    once. 'Orlando, f' also filters by state code.
    """
    name_part, _, state_part = query.partition(",")
    query_key, state_prefix = city_key(name_part), state_part.strip().casefold()
    if not query_key or limit < 1:
        return []

    best: dict[str, tuple[tuple[int, int, int, str, bool], CitySuggestion]] = {}
    for entry in entries:
        if state_prefix and not entry.state.casefold().startswith(state_prefix):
            continue
        tier = match_tier(entry.key, query_key)
        if tier is None:
            continue
        source = 0 if entry.source is CitySource.CATALOG else 1
        order = (tier, source, entry.rank, entry.name.casefold(), entry.is_alias)
        city = city_key(entry.name)
        if city in best and best[city][0] <= order:
            continue
        span = None if entry.is_alias else _matched_span(entry.name, query_key, tier)
        best[city] = (order, CitySuggestion(entry.name, entry.state, entry.source, span))
    return [suggestion for _, suggestion in sorted(best.values(), key=lambda pair: pair[0])[:limit]]


def _matched_span(name: str, query_key: str, tier: int) -> tuple[int, int] | None:
    pattern = r"[\s.]+".join(re.escape(part) for part in query_key.split(" "))
    anchor = "^" if tier == 0 else r"(?<=[\s.\-])"
    found = re.search(anchor + pattern, name, re.IGNORECASE)
    return found.span() if found else None


def build_city_directory(
    coordinates: Mapping[str, Coordinates],
    aliases: Mapping[str, str],
    extra_names: Iterable[str] = (),
    states: Mapping[str, str] | None = None,
) -> CityDirectory:
    canonical = {city_key(name): name for name in (*coordinates, *extra_names)}
    canonical.update({city_key(alias): target for alias, target in aliases.items()})
    return CityDirectory(canonical=canonical, coordinates=dict(coordinates), states=dict(states or {}))


def load_city_directory(cities_csv: Path, aliases_yaml: Path, extra_names: Iterable[str] = ()) -> CityDirectory:
    with cities_csv.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    coordinates = {row["name"]: (float(row["lat"]), float(row["lon"])) for row in rows}
    states = {row["name"]: row["state"] for row in rows}
    aliases = yaml.safe_load(aliases_yaml.read_text(encoding="utf-8")) or {}
    return build_city_directory(coordinates, {str(k): str(v) for k, v in aliases.items()}, extra_names, states)
