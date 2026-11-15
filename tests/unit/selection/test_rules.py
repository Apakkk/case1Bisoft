from pathlib import Path

import pytest
import yaml

from app.selection.rules import RulesError, parse_rules
from tests.case_data import DEFAULT_RULES_DATA, default_rules


def test_shipped_rules_file_matches_the_case_defaults() -> None:
    shipped = parse_rules(yaml.safe_load(Path("config/rules.yaml").read_text()))

    assert shipped == default_rules()


def test_unknown_filter_name_is_rejected_with_the_known_names() -> None:
    with pytest.raises(RulesError, match=r"unknown filter 'max_weight'.*cargo_type"):
        default_rules(filters=["distance_range", "max_weight"])


def test_unknown_ranking_name_is_rejected() -> None:
    with pytest.raises(RulesError, match="unknown ranking criterion 'no_such_criterion'"):
        default_rules(ranking=["no_such_criterion"])


def test_duplicate_ranking_names_are_rejected() -> None:
    with pytest.raises(RulesError, match="duplicate"):
        default_rules(ranking=["total_cost", "total_cost"])


def test_confidence_bands_must_be_ordered() -> None:
    with pytest.raises(RulesError, match="needs_review"):
        default_rules(confidence={"auto_accept": 0.5, "needs_review": 0.6, "hazardous_review": 0.15})


def test_missing_section_is_reported() -> None:
    data = {k: v for k, v in DEFAULT_RULES_DATA.items() if k != "catalog"}

    with pytest.raises(RulesError, match="catalog"):
        parse_rules(data)


def test_cargo_type_lookup_is_case_insensitive() -> None:
    rules = default_rules()

    assert rules.canonical_cargo_type("reefer") == "Reefer"
    assert rules.canonical_cargo_type(" HAZARDOUS ") == "Hazardous"
    assert rules.canonical_cargo_type("Flatrack") is None


def test_new_cargo_type_is_a_catalog_line() -> None:
    rules = default_rules(catalog={"cargo_types": ["Dry", "Reefer", "Hazardous", "Flatrack"], "container_sizes": [20]})

    assert rules.canonical_cargo_type("flatrack") == "Flatrack"
