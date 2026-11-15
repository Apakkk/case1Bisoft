"""Rules editing for the admin screen. The ranking order is data in rules.yaml, never code.

Hard constraints always run first; the ranking only orders the carriers that pass them.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.repositories.rules_repository import RulesStore
from app.selection.criteria import CRITERIA
from app.selection.rules import FINAL_TIE_BREAKER, RulesError, RuleSet


@dataclass(frozen=True, slots=True)
class CriterionOption:
    key: str
    label: str  # Turkish, capitalized for the screen


def criterion_option(key: str) -> CriterionOption:
    label = CRITERIA[key].label
    return CriterionOption(key, label[:1].upper() + label[1:])


class RulesService:
    def __init__(self, store: RulesStore) -> None:
        self._store = store

    def current(self) -> RuleSet:
        return self._store.get()

    def active_ranking(self) -> list[str]:
        """The editable part of the ranking (the final tie-breaker is fixed)."""
        return [name for name in self._store.get().ranking if name != FINAL_TIE_BREAKER]

    def save_ranking(self, ranking: Sequence[str]) -> RuleSet:
        unknown = [name for name in ranking if name not in CRITERIA]
        if unknown:
            raise RulesError(f"unknown ranking criterion: {', '.join(unknown)}")
        if len(set(ranking)) != len(ranking):
            raise RulesError("duplicate ranking criteria")
        return self._store.save_ranking(ranking)


def available_criteria(draft: Sequence[str]) -> list[str]:
    """Registered criteria not in the draft: a criterion added in code shows up here automatically."""
    return [key for key in CRITERIA if key not in draft and key != FINAL_TIE_BREAKER]


def edit_ranking(draft: Sequence[str], op: str, saved: Sequence[str]) -> list[str]:
    """Apply one editor action to a draft order: up:<key>, down:<key>, add:<key>, remove:<key> or reset."""
    items: list[str] = []
    for name in draft:  # drop unknown names, duplicates and the fixed tie-breaker
        if name in CRITERIA and name != FINAL_TIE_BREAKER and name not in items:
            items.append(name)
    action, _, key = op.partition(":")
    if action == "reset":
        return list(saved)
    if action == "add" and key in available_criteria(items):
        items.append(key)
    elif key in items:
        i = items.index(key)
        if action == "remove":
            items.pop(i)
        elif action == "up" and i > 0:
            items[i - 1], items[i] = items[i], items[i - 1]
        elif action == "down" and i < len(items) - 1:
            items[i + 1], items[i] = items[i], items[i + 1]
    return items
