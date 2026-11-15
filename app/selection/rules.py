"""Rule set parsed and validated from plain data (the YAML is read elsewhere: this module has no I/O)."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.selection.constraints import CONSTRAINTS
from app.selection.criteria import CRITERIA

FINAL_TIE_BREAKER = "name"


class RulesError(ValueError):
    """The rules file is invalid; the message says what to fix."""


@dataclass(frozen=True, slots=True)
class ConfidenceThresholds:
    auto_accept: float
    needs_review: float
    hazardous_review: float


@dataclass(frozen=True, slots=True)
class DistanceSettings:
    approximate_factor: Decimal
    boundary_warning_ratio: Decimal


@dataclass(frozen=True, slots=True)
class RuleSet:
    filters: tuple[str, ...]
    ranking: tuple[str, ...]  # always ends with FINAL_TIE_BREAKER
    cargo_types: tuple[str, ...]
    container_sizes: tuple[int, ...]
    confidence: ConfidenceThresholds
    distance: DistanceSettings

    def canonical_cargo_type(self, value: str) -> str | None:
        wanted = value.strip().casefold()
        return next((t for t in self.cargo_types if t.casefold() == wanted), None)


def parse_rules(data: Mapping[str, Any]) -> RuleSet:
    try:
        return _parse(data)
    except RulesError:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise RulesError(f"invalid rules: {error!r}") from error


def _parse(data: Mapping[str, Any]) -> RuleSet:
    filters = _names(data, "filters", CONSTRAINTS.keys(), "filter")
    ranking = _names(data, "ranking", CRITERIA.keys(), "ranking criterion")
    if FINAL_TIE_BREAKER not in ranking:
        ranking = (*ranking, FINAL_TIE_BREAKER)

    catalog = _section(data, "catalog")
    cargo_types = tuple(str(t) for t in _list(catalog, "catalog.cargo_types"))
    container_sizes = tuple(int(s) for s in _list(catalog, "catalog.container_sizes"))

    conf = _section(data, "confidence")
    confidence = ConfidenceThresholds(
        auto_accept=float(conf["auto_accept"]),
        needs_review=float(conf["needs_review"]),
        hazardous_review=float(conf["hazardous_review"]),
    )
    if not 0 < confidence.needs_review <= confidence.auto_accept <= 1:
        raise RulesError("confidence: expected 0 < needs_review <= auto_accept <= 1")
    if not 0 < confidence.hazardous_review < 1:
        raise RulesError("confidence: hazardous_review must be between 0 and 1")

    dist = _section(data, "distance")
    distance = DistanceSettings(
        approximate_factor=Decimal(str(dist["approximate_factor"])),
        boundary_warning_ratio=Decimal(str(dist["boundary_warning_ratio"])),
    )
    return RuleSet(filters, ranking, cargo_types, container_sizes, confidence, distance)


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise RulesError(f"missing or invalid section '{key}'")
    return value


def _list(data: Mapping[str, Any], path: str) -> Sequence[Any]:
    value = data.get(path.rsplit(".", 1)[-1])
    if not isinstance(value, list) or not value:
        raise RulesError(f"'{path}' must be a non-empty list")
    return value


def _names(data: Mapping[str, Any], key: str, known: Collection[str], kind: str) -> tuple[str, ...]:
    names = tuple(str(n) for n in _list(data, key))
    for name in names:
        if name not in known:
            raise RulesError(f"unknown {kind} '{name}'; known: {', '.join(sorted(known))}")
    if len(set(names)) != len(names):
        raise RulesError(f"duplicate names in '{key}'")
    return names
