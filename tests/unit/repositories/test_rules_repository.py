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
