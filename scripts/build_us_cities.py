"""Build config/us_cities.csv: US cities and towns with 5,000+ people.

Two public sources, joined by (name, state):
- GeoNames `cities5000` (https://www.geonames.org, CC BY 4.0): name, coordinates and population.
- US Census Bureau 2023 Gazetteer, places (public domain): what counts as a city. A Census place is an
  incorporated city, town, village or borough, or a census-designated place; never a neighbourhood.
  GeoNames alone also lists Washington's and Boston's neighbourhoods and New York's boroughs.

Kept: GeoNames rows in the US with a city feature code (PPL, PPLA..PPLA4, PPLC) whose name is a Census
place in the same state. One row per name, the most populous, because the rest of the system knows a
city by its name. A town missing here (e.g. a New Jersey township, which is not a Census place) is still
found through OpenRouteService when typed: the local list prefers a missing town to a wrong one.

    uv run python -m scripts.build_us_cities                      # downloads both files (~7 MB)
    uv run python -m scripts.build_us_cities GEONAMES.txt GAZ.txt  # or reads copies downloaded earlier
"""

import csv
import io
import re
import sys
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path

from app.clients.distance.cities import city_key

GEONAMES_URL = "https://download.geonames.org/export/dump/cities5000.zip"
CENSUS_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_place_national.zip"
OUT = Path("config/us_cities.csv")
CITY_CODES = frozenset({"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC"})
# Columns of a GeoNames dump line (readme.txt in the dump directory).
NAME, LAT, LON, FEATURE_CODE, COUNTRY, ADMIN1, POPULATION = 1, 4, 5, 7, 8, 10, 14

Row = tuple[str, str, float, float, int]  # name, state, lat, lon, population

_OFFICIAL_PREFIX = re.compile(r"^(?:city|town|village|borough) of\s+", re.IGNORECASE)  # 'City of Sammamish'
_NOTE = re.compile(r"\s*\([^)]*\)")  # 'Middlebury (village)', 'City of Milford (balance)'
# Census names end with the kind of place: 'Miami city', 'Brookline CDP', 'Juneau city and borough'.
_KIND = re.compile(
    r"\s+(?:city and borough|CDP|city|town|village|borough|municipality|township|comunidad|zona urbana|corporation)$"
)


def clean_name(raw: str) -> str | None:
    """The plain GeoNames name, or None for a row that is not a city a user would type.

    Dropped: former places ('(historical)'), and names joining several places ('Mililani Mauka / Launani
    Valley') or holding a comma, which would read as 'City, State'.
    """
    if "(historical)" in raw or "/" in raw or "," in raw:
        return None
    name = " ".join(_NOTE.sub("", _OFFICIAL_PREFIX.sub("", raw)).split())
    return name or None


def match_key(name: str) -> str:
    """Looser than city_key, for joining the two sources: no accents, hyphens; Saint = St, Mount = Mt."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    key = city_key(folded).replace("-", " ").replace("'", "")
    key = re.sub(r"\bsaint\b", "st", key)
    key = re.sub(r"\bsainte\b", "ste", key)
    key = re.sub(r"\bmount\b", "mt", key)
    return " ".join(key.split())


def census_names(raw: str) -> set[str]:
    """Match keys a Census place may go by: 'Boise City city' -> {'boise city', 'boise'}.

    Consolidated governments keep their city's name ('Nashville-Davidson metropolitan government
    (balance)' -> 'nashville'); Massachusetts town-cities drop 'Town' ('Weymouth Town city' -> 'weymouth');
    'Urban Honolulu CDP' -> 'honolulu'.
    """
    name = raw.strip()
    if "(balance)" in name or "government" in name or "urban county" in name or re.search(r"[-/].* County", name):
        name = re.split(r"[-/]", name)[0]
    name = _KIND.sub("", name.replace(" (balance)", ""))
    name = re.sub(r"^Urban ", "", name)
    name = re.sub(r" Town$", "", name)
    keys = {match_key(name)}
    if name.endswith(" City"):
        keys.add(match_key(name.removesuffix(" City")))
    return keys


def is_census_place(name: str, places: set[str]) -> bool:
    """'New York City' matches the Census 'New York city'. A part of a hyphenated name never matches:
    'Bayview-Hunters Point' (a San Francisco neighbourhood) is not the 'Bayview' CDP elsewhere in CA."""
    return match_key(name) in places or match_key(name.removesuffix(" City")) in places


def select(geonames: Iterable[list[str]], census: Iterable[list[str]]) -> list[Row]:
    """US cities and towns that are Census places, one per name (the most populous), sorted by name."""
    places: dict[str, set[str]] = defaultdict(set)
    for line in census:
        places[line[0]].update(census_names(line[3]))

    best: dict[str, Row] = {}
    for line in geonames:
        if line[COUNTRY] != "US" or line[FEATURE_CODE] not in CITY_CODES:
            continue
        name = clean_name(line[NAME])
        if name is None or not is_census_place(name, places[line[ADMIN1]]):
            continue
        row = (name, line[ADMIN1], float(line[LAT]), float(line[LON]), int(line[POPULATION] or 0))
        key = city_key(name)
        if key not in best or best[key][4] < row[4]:
            best[key] = row
    return sorted(best.values(), key=lambda r: (r[0].casefold(), r[1]))


def read_lines(source: Path | None, url: str, member: str, *, header: bool) -> Iterator[list[str]]:
    if source is not None:
        text = source.read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(url, timeout=60) as response:
            text = zipfile.ZipFile(io.BytesIO(response.read())).read(member).decode("utf-8")
    lines = csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    if header:
        next(lines, None)
    yield from lines


def write(rows: list[Row], out: Path) -> None:
    with out.open("w", encoding="utf-8", newline="") as f:
        f.write(
            "# US cities and towns with 5,000+ people, one row per name (the most populous). Names, coordinates\n"
            "# and population: GeoNames cities5000 (https://www.geonames.org, CC BY 4.0); only names that are\n"
            "# US Census Bureau 2023 Gazetteer places (public domain), so no neighbourhoods.\n"
            f"# Built by scripts/build_us_cities.py on {date.today()}.\n"
        )
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["name", "state", "lat", "lon", "population"])
        for name, state, lat, lon, population in rows:
            writer.writerow([name, state, f"{lat:.4f}", f"{lon:.4f}", population])


def main(argv: list[str]) -> None:
    geonames_file = Path(argv[1]) if len(argv) > 1 else None
    census_file = Path(argv[2]) if len(argv) > 2 else None
    rows = select(
        read_lines(geonames_file, GEONAMES_URL, "cities5000.txt", header=False),
        read_lines(census_file, CENSUS_URL, "2023_Gaz_place_national.txt", header=True),
    )
    write(rows, OUT)
    print(f"{OUT}: {len(rows)} cities")


if __name__ == "__main__":
    main(sys.argv)
