import os
from pathlib import Path

import pytest

from app.repositories.rules_repository import FileRulesRepository
from app.selection.rules import RulesError

SHIPPED = Path("config/rules.yaml").read_text()


def write(path: Path, text: str, mtime_ns: int) -> None:
    path.write_text(text)
    os.utime(path, ns=(mtime_ns, mtime_ns))  # explicit mtime: no sleeping, no flaky equality


def test_rules_are_reloaded_when_the_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    write(path, SHIPPED, 1_000_000_000)
    repo = FileRulesRepository(path)
    assert repo.get().ranking == ("total_cost", "hq_proximity", "name")

    swapped = SHIPPED.replace("  - total_cost\n  - hq_proximity", "  - hq_proximity\n  - total_cost")
    write(path, swapped, 2_000_000_000)

    assert repo.get().ranking == ("hq_proximity", "total_cost", "name")


def test_unchanged_file_is_served_from_cache(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    write(path, SHIPPED, 1_000_000_000)
    repo = FileRulesRepository(path)

    assert repo.get() is repo.get()


def test_invalid_yaml_raises_rules_error(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    write(path, "filters: [unclosed", 1_000_000_000)

    with pytest.raises(RulesError, match="not valid YAML"):
        FileRulesRepository(path).get()


def test_missing_file_raises_rules_error(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="not found"):
        FileRulesRepository(tmp_path / "nope.yaml").get()


SHIPPED_BLOCK = "ranking:\n  - total_cost\n  - hq_proximity\n  - name\n"


def test_save_ranking_rewrites_only_the_ranking_block(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    write(path, SHIPPED, 1_000_000_000)
    repo = FileRulesRepository(path)

    saved = repo.save_ranking(["hq_proximity", "total_cost"])

    new_block = "ranking:\n  - hq_proximity\n  - total_cost\n  - name\n"
    assert path.read_text() == SHIPPED.replace(SHIPPED_BLOCK, new_block)  # comments and other sections intact
    assert saved.ranking == repo.get().ranking == ("hq_proximity", "total_cost", "name")
    assert not (tmp_path / ".rules.yaml.tmp").exists()


def test_invalid_ranking_is_rejected_and_the_file_is_untouched(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    write(path, SHIPPED, 1_000_000_000)

    with pytest.raises(RulesError, match="unknown ranking criterion 'cheapest'"):
        FileRulesRepository(path).save_ranking(["cheapest"])

    assert path.read_text() == SHIPPED


def test_flow_style_ranking_is_rewritten_too(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    write(path, SHIPPED.replace(SHIPPED_BLOCK, "ranking: [total_cost, name]\n"), 1_000_000_000)

    FileRulesRepository(path).save_ranking(["hq_proximity"])

    assert "ranking:\n  - hq_proximity\n  - name\n" in path.read_text()
