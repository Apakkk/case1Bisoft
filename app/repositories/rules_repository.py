"""Reads rules.yaml, re-parsing only when the file changes (edits apply without a restart)."""

from pathlib import Path
from typing import Protocol

import yaml

from app.selection.rules import RulesError, RuleSet, parse_rules


class RulesSource(Protocol):
    def get(self) -> RuleSet: ...


class FileRulesRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: tuple[int, RuleSet] | None = None

    def get(self) -> RuleSet:
        try:
            mtime = self._path.stat().st_mtime_ns
        except FileNotFoundError as error:
            raise RulesError(f"rules file not found: {self._path}") from error
        if self._cache is not None and self._cache[0] == mtime:
            return self._cache[1]
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise RulesError(f"{self._path} is not valid YAML: {error}") from error
        rules = parse_rules(data if isinstance(data, dict) else {})
        self._cache = (mtime, rules)
        return rules
