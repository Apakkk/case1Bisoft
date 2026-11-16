"""Showroom view model: the trailer-panel homography, livery colours and the carrier facts the page shows."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from app.views.showroom import (
    CAMERAS,
    DOOR_SIZE,
    FACET_MARKINGS,
    PALETTE,
    PANEL_SIZE,
    SCENE,
    TRUCK,
    TRUCK_ORIGIN,
    Frame,
    accent,
    card,
    css_matrix3d,
    distance_range,
    lettering_size,
    marking_bounds,
    page_data,
    panel_homography,
    project,
    slug,
    turkish_list,
    unique_slugs,
)
from tests.case_data import CASE_CARRIERS, M_LOGISTICS, S_LOGISTICS

D = Decimal


@pytest.mark.parametrize("frame", [SCENE, TRUCK], ids=["scene", "truck"])
def test_homography_puts_the_lettering_box_on_the_measured_panel(frame: Frame) -> None:
    w, h = PANEL_SIZE
    matrix = panel_homography(frame.panel)

    corners = [project(matrix, x, y) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]

    for (x, y), (ex, ey) in zip(corners, frame.panel, strict=True):
        assert abs(x - ex) < 0.5 and abs(y - ey) < 0.5


@pytest.mark.parametrize("frame", [SCENE, TRUCK], ids=["scene", "truck"])
def test_homography_puts_the_door_box_on_the_measured_door(frame: Frame) -> None:
    w, h = DOOR_SIZE
    matrix = panel_homography(frame.door, DOOR_SIZE)

    corners = [project(matrix, x, y) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]

    for (x, y), (ex, ey) in zip(corners, frame.door, strict=True):
        assert abs(x - ex) < 0.5 and abs(y - ey) < 0.5


def test_the_cut_out_planes_are_the_scene_planes_shifted_by_the_crop() -> None:
    ox, oy = TRUCK_ORIGIN
    assert TRUCK.panel == tuple((x - ox, y - oy) for x, y in SCENE.panel)
    assert TRUCK.door == tuple((x - ox, y - oy) for x, y in SCENE.door)


@pytest.mark.parametrize("facet", ["rate", "distance", "equipment", "cargo"])
def test_each_facet_camera_frames_its_marking(facet: str) -> None:
    """The zoom is meaningful: the camera box holds the marking that shows the facet's value, inside the photo."""
    mx, my, mw, mh = marking_bounds(*FACET_MARKINGS[facet])
    cx, cy, cw, ch = CAMERAS[facet].box

    assert cx <= mx and cy <= my and mx + mw <= cx + cw and my + mh <= cy + ch
    assert cx >= 0 and cy >= 0 and cx + cw <= SCENE.width and cy + ch <= SCENE.height


def test_markings_stay_inside_their_plane() -> None:
    for quad, size, (x, y, w, h) in FACET_MARKINGS.values():
        assert quad in (SCENE.panel, SCENE.door)
        assert x >= 0 and y >= 0 and x + w <= size[0] and y + h <= size[1]


def test_matrix3d_is_plain_css_numbers() -> None:
    css = css_matrix3d(panel_homography(SCENE.panel))

    assert css.startswith("matrix3d(") and css.endswith(")")
    values = css[len("matrix3d(") : -1].split(", ")
    assert len(values) == 16
    assert all("e" not in v and v not in ("-0", "") for v in values)  # no exponent notation, no negative zero
    assert SCENE.matrix == css


def test_accent_is_stable_and_ignores_letter_case() -> None:
    assert accent("S-Logistics") == accent("s-logistics") == accent("S-LOGISTICS")
    assert accent("S-Logistics") in PALETTE


def test_case_carriers_get_different_accents() -> None:
    assert len({accent(c.name) for c in CASE_CARRIERS}) == len(CASE_CARRIERS)


def test_long_names_get_smaller_lettering_on_two_lines() -> None:
    assert lettering_size("S-Logistics") > lettering_size("Anadolu Uluslararası Taşımacılık") >= 40


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (None, None, "Sınırsız"),
        (None, D(300), "≤ 300 mil"),
        (D(250), None, "≥ 250 mil"),
        (D(100), D(500), "100–500 mil"),
    ],
)
def test_distance_range_uses_the_carriers_table_wording(low: D | None, high: D | None, expected: str) -> None:
    assert distance_range(low, high) == expected


def test_turkish_list() -> None:
    assert turkish_list([]) == ""
    assert turkish_list(["40"]) == "40"
    assert turkish_list(["40", "45"]) == "40 ve 45"
    assert turkish_list(["20", "40", "45"]) == "20, 40 ve 45"


def test_card_lists_the_four_facets_from_real_data() -> None:
    facets = {f["key"]: f for f in card(M_LOGISTICS)["facets"]}

    assert list(facets) == ["rate", "distance", "equipment", "cargo"]
    assert facets["rate"]["value"] == "$1.00 / mil"
    assert facets["distance"]["value"] == "Sınırsız"
    assert facets["equipment"]["value"] == "20 · 40 ft"
    assert facets["cargo"]["value"] == "Dry · Hazardous · Reefer"
    assert "taşıyabilir" in facets["cargo"]["text"]


def test_card_carries_what_is_painted_on_the_truck() -> None:
    data = card(M_LOGISTICS)

    assert data["rate_line"] == "$1.00 / mil"
    assert data["size_mark"] == "20 · 40 FT"
    assert data["cargo_badges"] == ["DRY", "REEFER"]  # Hazardous is the diamond, not a badge
    assert data["hazardous"] is True
    assert [line["text"] for line in data["door"]] == ["M-Logistics", "Houston merkezli", "Mesafe sınırsız"]
    assert [line["text"] for line in card(S_LOGISTICS)["door"]][2] == "Mesafe ≤ 300 mil"


def test_card_carries_the_note_and_the_hazardous_flag() -> None:
    noted = replace(S_LOGISTICS, description="Hafta sonu çalışmaz.")

    data = card(noted)

    assert data["note"] == "Hafta sonu çalışmaz."
    assert data["hazardous"] is False
    assert "taşımaz" in data["facets"][3]["text"]


def test_page_data_is_json_serialisable() -> None:
    data = page_data(list(CASE_CARRIERS))

    assert json.loads(json.dumps(data))["carriers"][0]["name"] == CASE_CARRIERS[0].name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("A-Logistics", "a-logistics"),
        ("M Logistics Co.", "m-logistics-co"),
        ("Öz Taşımacılık", "oz-tasimacilik"),
        ("İzmir Lojistik", "izmir-lojistik"),
        ("Café & Co", "cafe-co"),
        ("***", "firma"),
    ],
)
def test_the_url_part_is_the_carriers_name(name: str, expected: str) -> None:
    assert slug(name) == expected


def test_names_with_the_same_url_part_get_a_number() -> None:
    carriers = [replace(M_LOGISTICS, name=n) for n in ("A Logistics", "A-Logistics", "a.logistics", "B-Logistics")]

    assert unique_slugs(carriers) == ["a-logistics", "a-logistics-2", "a-logistics-3", "b-logistics"]
