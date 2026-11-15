"""City name normalization and known coordinates (config/cities.csv + config/city_aliases.yaml)."""

import csv
import re
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

_STATE_SUFFIX = re.compile(r",\s*[A-Za-z]{2}$")

Coordinates = tuple[float, float]  # (lat, lon)


def _key(name: str) -> str:
    return " ".join(name.replace(".", " ").split()).casefold()


@dataclass(frozen=True, slots=True)
class CityDirectory:
    canonical: Mapping[str, str]  # lookup key -> canonical name (known cities and aliases)
    coordinates: Mapping[str, Coordinates]  # canonical name -> (lat, lon)

    def normalize(self, raw: str) -> str:
        """'ft. lauderdale' -> 'Fort Lauderdale', 'Miami, FL' -> 'Miami'; unknown names are title-cased."""
        cleaned = _STATE_SUFFIX.sub("", raw.strip())
        known = self.canonical.get(_key(cleaned))
        if known is not None:
            return known
        return string.capwords(" ".join(cleaned.split()))

    def coordinates_of(self, city: str) -> Coordinates | None:
        return self.coordinates.get(city)


def build_city_directory(
    coordinates: Mapping[str, Coordinates],
    aliases: Mapping[str, str],
    extra_names: Iterable[str] = (),
) -> CityDirectory:
    canonical = {_key(name): name for name in (*coordinates, *extra_names)}
    canonical.update({_key(alias): target for alias, target in aliases.items()})
    return CityDirectory(canonical=canonical, coordinates=dict(coordinates))


def load_city_directory(cities_csv: Path, aliases_yaml: Path, extra_names: Iterable[str] = ()) -> CityDirectory:
    with cities_csv.open(encoding="utf-8", newline="") as f:
        coordinates = {row["name"]: (float(row["lat"]), float(row["lon"])) for row in csv.DictReader(f)}
    aliases = yaml.safe_load(aliases_yaml.read_text(encoding="utf-8")) or {}
    return build_city_directory(coordinates, {str(k): str(v) for k, v in aliases.items()}, extra_names)
