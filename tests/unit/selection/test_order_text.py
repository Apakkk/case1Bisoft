"""Container size from free text: only with a unit, only one catalog size. A container count is detected."""

import pytest

from app.selection.order_text import parse_container_size, several_containers

SIZES = (20, 40, 45)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("40 ft dry", 40),
        ("40-foot container", 40),
        ("40'lık konteyner", 40),
        ("20’lik konteynerde donmuş karides", 20),
        ("40lık", 40),
        ("45HC reefer", 45),
        ("40' HC", 40),
        ("1x40HC", 40),
        ("2x40ft", 40),
        ("ayın 20'sinde teslim, 40'lık dolu", 40),  # the date is not a second size
    ],
)
def test_a_size_with_a_unit_is_read(text: str, expected: int) -> None:
    assert parse_container_size(text, SIZES) == expected


@pytest.mark.parametrize(
    "text",
    [
        "40 ton",
        "20 tons of steel",
        "ayın 20'sinde teslim",
        "20'de teslim",
        "40 ft ve 20 ft",  # two sizes: ambiguous
        "53 ft",  # not in the catalog
        "1240 ft",  # part of a longer number
        "12.40 ft",
        "donmuş karides",
    ],
)
def test_anything_else_is_left_to_jev(text: str) -> None:
    assert parse_container_size(text, SIZES) is None


@pytest.mark.parametrize(
    ("text", "phrases"),
    [
        ("3 adet 40'lık kuru yük", ["3 adet"]),
        ("İki tane 20'lik", ["İki tane"]),
        ("üç konteyner dondurulmuş et", ["üç konteyner"]),
        ("three containers of shoes", ["three containers"]),
        ("2x40HC", ["2x40"]),
        ("2 x 40 konteyner", ["2 x 40"]),  # one count, not two
        ("1 adet 40'lık ve 1 adet 20'lik", ["1 adet", "1 adet"]),  # two in total
    ],
)
def test_more_than_one_container_is_noticed(text: str, phrases: list[str]) -> None:
    assert several_containers(text) == phrases


@pytest.mark.parametrize(
    "text",
    [
        "1 adet 40'lık",
        "1x40HC",
        "40'lık konteyner",
        "40 ton çelik",  # a weight, not a count
        "1920x1080",
        "on container ship",  # "on" is not counted as ten
        "S-Logistics olmasın",
    ],
)
def test_one_container_or_no_count_is_not_flagged(text: str) -> None:
    assert several_containers(text) == []
