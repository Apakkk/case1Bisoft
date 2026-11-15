"""Reads rules.yaml, re-parsing only when the file changes (edits apply without a restart).

The admin rules page writes the `ranking` block back. Only that block is rewritten, so the comments
and every other section of the file stay exactly as the author left them.
"""

import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.selection.rules import FINAL_TIE_BREAKER, RulesError, RuleSet, parse_rules

logger = logging.getLogger(__name__)

# `ranking:` followed by block-style items ("  - total_cost"), or in flow style ("ranking: [a, b]").
_RANKING_BLOCK = re.compile(r"^ranking:[ \t]*(?:#[^\n]*)?\n(?:[ \t]+-[^\n]*(?:\n|$))+", re.MULTILINE)
_RANKING_FLOW = re.compile(r"^ranking:[ \t]*\[[^\]\n]*\][^\n]*(?:\n|$)", re.MULTILINE)


class RulesSource(Protocol):
    def get(self) -> RuleSet: ...

    @property
    def problem(self) -> str | None: ...  # Turkish warning while a broken edit is being ignored


class RulesStore(RulesSource, Protocol):
    def save_ranking(self, ranking: Sequence[str]) -> RuleSet: ...


class FileRulesRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: tuple[int, RuleSet] | None = None
        self.problem: str | None = None  # Turkish warning while a broken edit is being ignored

    def get(self) -> RuleSet:
        try:
            mtime = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            return self._last_good(RulesError(f"rules file not found: {self._path}"), None)
        if self._cache is not None and self._cache[0] == mtime:
            return self._cache[1]
        try:
            rules = parse_rules(self._load(self._path.read_text(encoding="utf-8")))
        except RulesError as error:
            return self._last_good(error, mtime)
        self._cache, self.problem = (mtime, rules), None
        return rules

    def _last_good(self, error: RulesError, mtime: int | None) -> RuleSet:
        """A broken edit keeps the last valid rules and says so; with no valid rules yet it is an error."""
        if self._cache is None:
            raise error
        logger.warning("rules file %s ignored: %s", self._path, error)
        self.problem = f"{self._path.name} geçersiz ({error}); son geçerli kurallar kullanılıyor."
        if mtime is not None:
            self._cache = (mtime, self._cache[1])  # the same broken file is not parsed again on every request
        return self._cache[1]

    def save_ranking(self, ranking: Sequence[str]) -> RuleSet:
        """Rewrite the ranking block; validated before writing, so an invalid order never reaches the file."""
        names = [n for n in ranking if n != FINAL_TIE_BREAKER] + [FINAL_TIE_BREAKER]
        text = self._path.read_text(encoding="utf-8")
        block = "ranking:\n" + "".join(f"  - {name}\n" for name in names)
        new_text, count = _RANKING_BLOCK.subn(block, text, count=1)
        if count == 0:
            new_text, count = _RANKING_FLOW.subn(block, text, count=1)
        if count == 0:
            raise RulesError(f"could not find the 'ranking' list in {self._path}")

        rules = parse_rules(self._load(new_text))  # raises RulesError: the file is left untouched
        if list(rules.ranking) != names:
            raise RulesError(f"could not rewrite the 'ranking' list in {self._path} safely")

        tmp = self._path.with_name(f".{self._path.name}.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        os.replace(tmp, self._path)  # atomic: a request never reads a half-written file
        self._cache = None
        return rules

    def _load(self, text: str) -> dict[str, Any]:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise RulesError(f"{self._path} is not valid YAML: {error}") from error
        return data if isinstance(data, dict) else {}
