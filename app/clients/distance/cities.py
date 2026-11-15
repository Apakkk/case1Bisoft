"""Known US cities: name normalization, coordinates, state codes, suggestions and "did you mean".

Two shipped sources: the case catalog (config/cities.csv + config/city_aliases.yaml) and US cities with
5,000+ people (config/us_cities.csv, GeoNames + Census places, built by scripts/build_us_cities.py).
The catalog wins a shared name. Cities found later through OpenRouteService live in the `cities` table.
"""

import csv
import difflib
import re
import string
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TextIO

import yaml

from app.models.city import City, CitySource, CitySuggestion, Place

_STATE_SUFFIX = re.compile(r",\s*[A-Za-z]{2}$")
_WORD_START = re.compile(r"[ \-]")
_WORD = re.compile(r"[^\s.\-]+")

MIN_WORD_MATCH_CHARS = 3  # 'a' must not suggest Los Angeles; 'lau' may suggest Fort Lauderdale
_CLOSE_MATCH_CUTOFF = 0.75  # 'tamap' -> 'tampa' scores 0.8; unrelated names score far lower

Coordinates = tuple[float, float]  # (lat, lon)

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}  # fmt: skip
_STATE_CODES = frozenset(US_STATES.values())


def city_key(name: str) -> str:
    """Comparison key: case, dots and extra spaces do not matter ('ST. louis ' == 'St. Louis').

    Turkish 'İ'/'ı' count as 'i' ('MİAMİ' typed with Caps Lock on a Turkish keyboard is Miami).
    """
    return " ".join(name.replace(".", " ").replace("İ", "i").replace("ı", "i").split()).casefold()


def split_qualifier(raw: str) -> tuple[str, str | None]:
    """'Paris, France' -> ('Paris', 'France'); 'Paris' -> ('Paris', None). The last comma counts."""
    name, comma, rest = raw.rpartition(",")
    if not comma:
        return " ".join(raw.split()), None
    return " ".join(name.split()), " ".join(rest.split())


def state_code(text: str) -> str | None:
    """'FL', 'fl', 'Florida', 'd.c.' -> the two-letter US state code; anything else (a country) -> None."""
    key = city_key(text).replace(" ", "")
    if key.upper() in _STATE_CODES:
        return key.upper()
    return US_STATES.get(city_key(text))


def word_tails(name: str) -> tuple[str, ...]:
    """Keys of the name from each later word that starts with a capital: what a word-start match uses.

    'Hamptons at Boca Raton' -> ('boca raton', 'raton'): lower-case joining words ('at', 'by', 'the') do not
    count, so 'at' does not suggest it.
    """
    words = list(_WORD.finditer(name))[1:]
    return tuple(city_key(name[w.start() :]) for w in words if w.group()[0].isupper())


@dataclass(frozen=True, slots=True)
class CityEntry:
    """Something a query can match: a city name, or an alias that stands for one."""

    key: str  # city_key of the matched text
    name: str  # the city that is suggested
    state: str
    source: CitySource
    is_alias: bool = False
    rank: int = 0  # cities found online: the routing service's relevance order
    population: int = 0  # shipped cities: more people first among equally good matches
    tails: tuple[str, ...] = ()  # word_tails(name); empty for an alias, which matches from its start only

    @classmethod
    def of(cls, city: City, source: CitySource, rank: int = 0) -> "CityEntry":
        return cls(city_key(city.name), city.name, city.state, source, rank=rank, tails=word_tails(city.name))


@dataclass(frozen=True)
class CityDirectory:
    canonical: Mapping[str, str]  # lookup key -> canonical name (known cities and aliases)
    coordinates: Mapping[str, Coordinates]  # canonical name -> (lat, lon)
    states: Mapping[str, str] = field(default_factory=dict)  # canonical name -> state code
    population: Mapping[str, int] = field(default_factory=dict)  # canonical name -> people (us_cities.csv)

    def lookup(self, raw: str) -> str | None:
        """Canonical name of a known city or alias ('Miami, FL' -> 'Miami'), or None. The state is not checked."""
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

    def state_of(self, city: str) -> str:
        return self.states.get(city, "")

    def place(self, city: str) -> Place:
        return Place(city, self.state_of(city))

    def close_matches(self, raw: str, limit: int = 3) -> list[Place]:
        """Known cities spelled like `raw`, for "did you mean": 'Tamap' -> Tampa, 'Jacksonvile' -> Jacksonville."""
        key = city_key(split_qualifier(raw)[0])
        if not key:
            return []
        found = difflib.get_close_matches(key, self.canonical, n=limit * 2, cutoff=_CLOSE_MATCH_CUTOFF)
        names = list(dict.fromkeys(self.canonical[k] for k in found))  # aliases of one city count once
        return [self.place(name) for name in names[:limit]]

    def entries(self) -> tuple[CityEntry, ...]:
        return self._entries

    @cached_property
    def _entries(self) -> tuple[CityEntry, ...]:
        entries = []
        for key, name in self.canonical.items():
            alias = key != city_key(name)
            entries.append(
                CityEntry(
                    key,
                    name,
                    self.state_of(name),
                    CitySource.CATALOG,
                    is_alias=alias,
                    population=self.population.get(name, 0),
                    tails=() if alias else word_tails(name),
                )
            )
        return tuple(entries)


def match_tier(key: str, query_key: str, tails: Iterable[str] | None = None) -> int | None:
    """0 = the name starts with the query, 1 = a later word does ('lau' in 'Fort Lauderdale'), None = no match.

    Letters in the middle of a word do not count: 'o' suggests Orlando, not Boston. A later word counts only
    from MIN_WORD_MATCH_CHARS letters on, so 'a' lists cities starting with A, not Los Angeles.
    `tails`: the entry's word_tails; None derives them from the key (every later word).
    """
    if key.startswith(query_key):
        return 0
    if len(query_key) < MIN_WORD_MATCH_CHARS:
        return None
    later = tails if tails is not None else (key[gap.end() :] for gap in _WORD_START.finditer(key))
    return 1 if any(tail.startswith(query_key) for tail in later) else None


def rank_suggestions(query: str, entries: Iterable[CityEntry], limit: int = 5) -> list[CitySuggestion]:
    """Best `limit` cities for what the user typed so far.

    Order: the name starts with the query -> a later word does. Within each, shipped cities by population
    (so 'a' lists Austin, Albuquerque, Atlanta...), then cities found online in the routing service's
    relevance order. Each city appears once. 'Orlando, f' also filters by state code.
    """
    name_part, _, state_part = query.partition(",")
    query_key, state_prefix = city_key(name_part), state_part.strip().casefold()
    if not query_key or limit < 1:
        return []

    best: dict[str, tuple[tuple[int, int, int, int, str, bool], CitySuggestion]] = {}
    for entry in entries:
        if state_prefix and not entry.state.casefold().startswith(state_prefix):
            continue
        tier = match_tier(entry.key, query_key, entry.tails)
        if tier is None:
            continue
        source = 0 if entry.source is CitySource.CATALOG else 1
        order = (tier, source, -entry.population, entry.rank, entry.name.casefold(), entry.is_alias)
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
    us_cities: Iterable[tuple[City, int]] = (),
) -> CityDirectory:
    """Catalog cities and aliases first; then `us_cities` (city, population) for names not taken yet.

    A catalog city keeps its coordinates and state and takes the population of the same name ('New York'
    gets New York City's through its alias).
    """
    canonical = {city_key(name): name for name in (*coordinates, *extra_names)}
    canonical.update({city_key(alias): target for alias, target in aliases.items()})
    all_coordinates, all_states = dict(coordinates), dict(states or {})
    population: dict[str, int] = {}
    for city, people in us_cities:
        key = city_key(city.name)
        known = canonical.get(key)
        if known is not None:
            population[known] = max(population.get(known, 0), people)
            continue
        canonical[key] = city.name
        all_coordinates[city.name] = (city.lat, city.lon)
        all_states[city.name] = city.state
        population[city.name] = people
        folded = city_key(_without_accents(city.name))  # 'canon city' finds 'Cañon City'
        canonical.setdefault(folded, city.name)
    return CityDirectory(canonical, all_coordinates, all_states, population)


def load_city_directory(
    cities_csv: Path, aliases_yaml: Path, extra_names: Iterable[str] = (), us_cities_csv: Path | None = None
) -> CityDirectory:
    with cities_csv.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(_data_lines(f)))
    coordinates = {row["name"]: (float(row["lat"]), float(row["lon"])) for row in rows}
    states = {row["name"]: row["state"] for row in rows}
    aliases = yaml.safe_load(aliases_yaml.read_text(encoding="utf-8")) or {}
    us_cities: list[tuple[City, int]] = []
    if us_cities_csv is not None:
        with us_cities_csv.open(encoding="utf-8", newline="") as f:
            us_cities = [
                (City(row["name"], row["state"], float(row["lat"]), float(row["lon"])), int(row["population"]))
                for row in csv.DictReader(_data_lines(f))
            ]
    return build_city_directory(
        coordinates, {str(k): str(v) for k, v in aliases.items()}, extra_names, states, us_cities
    )


def _data_lines(f: TextIO) -> Iterator[str]:
    """CSV lines without the '# ...' provenance header."""
    return (line for line in f if not line.startswith("#"))


def _without_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
