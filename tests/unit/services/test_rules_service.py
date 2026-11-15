"""Ranking editor actions (pure) and validation before anything reaches rules.yaml."""

from collections.abc import Sequence

import pytest

from app.selection.rules import RulesError, RuleSet
from app.services.rules_service import RulesService, available_criteria, edit_ranking
from tests.case_data import default_rules

SAVED = ["total_cost", "hq_proximity"]


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        ("up:hq_proximity", ["hq_proximity", "total_cost"]),
        ("down:total_cost", ["hq_proximity", "total_cost"]),
        ("up:total_cost", SAVED),  # already first
        ("down:hq_proximity", SAVED),  # already last
        ("remove:total_cost", ["hq_proximity"]),
        ("add:total_cost", SAVED),  # already present
        ("add:requested", SAVED),  # not a rule: a requested carrier always comes first
        ("bogus:total_cost", SAVED),
        ("", SAVED),
    ],
)
def test_editor_actions(op: str, expected: list[str]) -> None:
    assert edit_ranking(SAVED, op, SAVED) == expected


def test_add_appends_an_unused_criterion_and_reset_restores_the_saved_order() -> None:
    draft = edit_ranking(["total_cost"], "add:hq_proximity", SAVED)

    assert draft == ["total_cost", "hq_proximity"]
    assert edit_ranking(["hq_proximity"], "reset", SAVED) == SAVED


def test_unknown_duplicate_and_fixed_names_are_dropped_from_a_posted_draft() -> None:
    assert edit_ranking(["total_cost", "nope", "total_cost", "name", "requested"], "", SAVED) == ["total_cost"]


def test_available_criteria_lists_registered_ones_not_in_use() -> None:
    available = available_criteria(["total_cost"])

    assert "hq_proximity" in available
    assert "total_cost" not in available and "name" not in available


class MemoryStore:
    def __init__(self) -> None:
        self.rules = default_rules()
        self.saved: list[list[str]] = []

    def get(self) -> RuleSet:
        return self.rules

    def save_ranking(self, ranking: Sequence[str]) -> RuleSet:
        self.saved.append(list(ranking))
        self.rules = default_rules(ranking=list(ranking))
        return self.rules


def test_service_validates_before_saving() -> None:
    store = MemoryStore()
    service = RulesService(store)

    with pytest.raises(RulesError):
        service.save_ranking(["total_cost", "total_cost"])
    with pytest.raises(RulesError):
        service.save_ranking(["requested"])
    service.save_ranking(["hq_proximity", "total_cost"])

    assert store.saved == [["hq_proximity", "total_cost"]]
    assert service.active_ranking() == ["hq_proximity", "total_cost"]
