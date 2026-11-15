"""View model for the home page's truck showroom: card data, livery colours and the perspective of the markings.

Every carrier is drawn as the same truck photo with its own livery, and each fact sits where a real truck would carry
it: the name with the rate under it on the trailer curtain, a container-size stencil at the curtain's rear corner,
cargo badges (and a hazmat diamond) at its front corner, the home city and distance range on the cab door. Each
marking is an HTML box laid out in its plane's own units and mapped onto that plane's four measured corners with a
CSS ``matrix3d`` homography, so it follows the photo's perspective. The matrices are computed here, so the page is
right before any script runs.

The detail view's camera only goes where a facet's value is painted: each facet's camera box is its marking's
projected corners plus a margin (tests check that every camera contains its marking).
"""

import zlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models.carrier import Carrier
from app.selection.formatting import fmt_miles, fmt_rate

type Point = tuple[float, float]
type Quad = tuple[Point, Point, Point, Point]  # top-left, top-right, bottom-right, bottom-left
type Box = tuple[float, float, float, float]  # left, top, width, height

# The curtain's box in its own units. A curtain side is about 13.5 m x 2.7 m, so 5:1 keeps letters unstretched.
PANEL_SIZE: Point = (1000.0, 200.0)
# The cab door's box: the flat part below the window, right of the handle (about 0.7 m x 0.65 m).
DOOR_SIZE: Point = (300.0, 270.0)

# Measured in static/home/scene.jpg pixels. The curtain sits inside the rails and corner posts. The door's top and
# bottom edges run to the same vanishing point as the trailer's (x = -552 on the horizon y = 397).
SCENE_PANEL: Quad = ((571.0, 199.0), (1172.0, 93.0), (1172.0, 396.0), (572.0, 397.0))
SCENE_DOOR: Quad = ((1360.0, 304.0), (1440.0, 300.1), (1440.0, 383.5), (1360.0, 384.0))

# static/home/truck.webp is the truck cut out of scene.jpg (same pixels), cropped at this origin.
TRUCK_ORIGIN: Point = (552.0, 59.0)

# Where each marking sits in its plane's units. The page places the markings from these same numbers.
MARK_BOX: Box = (222.0, 12.0, 566.0, 176.0)  # curtain, middle: the name with the rate line under it
SIZE_BOX: Box = (24.0, 122.0, 150.0, 58.0)  # curtain, rear-lower corner: container-size stencil
CARGO_BOX: Box = (812.0, 14.0, 176.0, 172.0)  # curtain, front edge: cargo badges, hazmat diamond at the bottom
DOOR_BOX: Box = (0.0, 0.0, *DOOR_SIZE)  # the whole door plate: name, home city, distance range

# The rear axles, framed together with the size stencil (scene pixels).
AXLES: Box = (615.0, 400.0, 205.0, 105.0)


@dataclass(frozen=True)
class Frame:
    """An image and where its curtain and cab door are."""

    src: str  # path under /static
    width: int
    height: int
    panel: Quad
    door: Quad

    @property
    def matrix(self) -> str:
        return css_matrix3d(panel_homography(self.panel))

    @property
    def door_matrix(self) -> str:
        return css_matrix3d(panel_homography(self.door, DOOR_SIZE))


@dataclass(frozen=True)
class Camera:
    """What the detail view must show for a facet, and how far it may enlarge the photo (CSS px per image px)."""

    box: Box
    zoom: float


def _shift(quad: Quad, origin: Point) -> Quad:
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = quad
    ox, oy = origin
    return ((ax - ox, ay - oy), (bx - ox, by - oy), (cx - ox, cy - oy), (dx - ox, dy - oy))


def panel_homography(quad: Quad, size: Point = PANEL_SIZE) -> tuple[float, ...]:
    """The 16 column-major matrix3d values that map the box (0,0)-(width,height) onto quad (Heckbert, 1989)."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad
    dx1, dx2, sx = x1 - x2, x3 - x2, x0 - x1 + x2 - x3
    dy1, dy2, sy = y1 - y2, y3 - y2, y0 - y1 + y2 - y3
    den = dx1 * dy2 - dx2 * dy1
    g = (sx * dy2 - dx2 * sy) / den
    h = (dx1 * sy - sx * dy1) / den
    a, b, c = x1 - x0 + g * x1, x3 - x0 + h * x3, x0
    d, e, f = y1 - y0 + g * y1, y3 - y0 + h * y3, y0
    w, ht = size
    return (a / w, d / w, 0.0, g / w, b / ht, e / ht, 0.0, h / ht, 0.0, 0.0, 1.0, 0.0, c, f, 0.0, 1.0)


def project(matrix: tuple[float, ...], x: float, y: float) -> Point:
    """Where matrix3d puts the point (x, y) of the element (transform-origin 0 0)."""
    m = matrix
    w = m[3] * x + m[7] * y + m[15]
    return ((m[0] * x + m[4] * y + m[12]) / w, (m[1] * x + m[5] * y + m[13]) / w)


def css_matrix3d(matrix: tuple[float, ...]) -> str:
    return "matrix3d(" + ", ".join(_number(v) for v in matrix) + ")"


def _number(value: float) -> str:
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def marking_bounds(quad: Quad, size: Point, box: Box) -> Box:
    """The scene rectangle around a marking: its box's four corners projected onto the photo."""
    matrix = panel_homography(quad, size)
    x, y, w, h = box
    corners = [project(matrix, cx, cy) for cx, cy in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _padded(box: Box, ratio: float) -> Box:
    x, y, w, h = box
    pad = max(w, h) * ratio
    return (x - pad, y - pad, w + 2 * pad, h + 2 * pad)


def _union(a: Box, b: Box) -> Box:
    left, top = min(a[0], b[0]), min(a[1], b[1])
    right, bottom = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (left, top, right - left, bottom - top)


SCENE = Frame("home/scene.jpg", 1789, 576, SCENE_PANEL, SCENE_DOOR)
TRUCK = Frame("home/truck.webp", 1056, 498, _shift(SCENE_PANEL, TRUCK_ORIGIN), _shift(SCENE_DOOR, TRUCK_ORIGIN))

# Facet -> the marking that shows its value (plane, plane size, box). The page lights the same marking.
FACET_MARKINGS: dict[str, tuple[Quad, Point, Box]] = {
    "rate": (SCENE_PANEL, PANEL_SIZE, MARK_BOX),
    "distance": (SCENE_DOOR, DOOR_SIZE, DOOR_BOX),
    "equipment": (SCENE_PANEL, PANEL_SIZE, SIZE_BOX),
    "cargo": (SCENE_PANEL, PANEL_SIZE, CARGO_BOX),
}

CAMERAS: dict[str, Camera] = {
    "overview": Camera((520.0, 40.0, 1120.0, 520.0), 1.5),  # the whole truck: where the detail view lands
    "rate": Camera(_padded(marking_bounds(*FACET_MARKINGS["rate"]), 0.1), 1.5),
    "distance": Camera(_padded(marking_bounds(*FACET_MARKINGS["distance"]), 0.35), 2.0),  # a small door: closer
    "equipment": Camera(_union(_padded(marking_bounds(*FACET_MARKINGS["equipment"]), 0.25), AXLES), 1.5),
    "cargo": Camera(_padded(marking_bounds(*FACET_MARKINGS["cargo"]), 0.3), 1.6),
}


def marking_style(box: Box) -> str:
    """Inline CSS that puts a marking at its box inside its plane."""
    x, y, w, h = box
    return f"left: {_number(x)}px; top: {_number(y)}px; width: {_number(w)}px; height: {_number(h)}px"


MARKING_STYLES = {"mark": marking_style(MARK_BOX), "size": marking_style(SIZE_BOX), "cargo": marking_style(CARGO_BOX)}

# Accents tuned for a dark stage; a carrier keeps its colour because it is picked from the name.
PALETTE = (
    "#a9c1e8",  # silver-blue
    "#ff4f5e",  # signal red
    "#b6ff3b",  # acid green
    "#3fe0ff",  # cyan
    "#a98bff",  # violet
    "#ffb43a",  # amber
    "#ff6fb1",  # rose
    "#4dffc3",  # mint
)

_HAZARDOUS = "Hazardous"


def accent(name: str) -> str:
    """The carrier's colour: stable across restarts and database resets (ids are not), same for any letter case."""
    return PALETTE[zlib.crc32(name.lower().encode()) % len(PALETTE)]


def lettering_size(name: str) -> int:
    """A first font size for the name on the curtain (units); the page refines it. Long names take two lines."""
    width = MARK_BOX[2] * 0.98
    one_line = width / (0.5 * max(len(name), 1))
    if one_line >= 60 or " " not in name.strip():
        return int(min(104, one_line))
    longest = max(len(part) for part in _two_lines(name))
    return int(min(68, width / (0.5 * longest)))


def line_size(text: str, width: float, largest: float) -> int:
    """A first font size that keeps one line of text within width (units)."""
    return int(min(largest, width / (0.55 * max(len(text), 1))))


def badge_size(badges: list[str], hazardous: bool) -> int:
    """A first font size for the cargo badges: they stack in one column above the hazmat diamond, wrapping inside."""
    _, _, width, height = CARGO_BOX
    room = height - (80 if hazardous else 0)
    inner = width - 24  # badge padding and border
    for size in range(18, 7, -1):
        lines = [-(-len(b) * 0.62 * size // inner) for b in badges]  # ceil
        needed = sum(n * size * 1.05 + 14 for n in lines) + 6 * max(len(badges) - 1, 0)
        if needed <= room and all(len(w) * 0.62 * size <= inner for b in badges for w in b.split()):
            return size
    return 8


def _two_lines(name: str) -> tuple[str, str]:
    """Split at the space closest to the middle."""
    words = name.split()
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:best]), " ".join(words[best:])


def distance_range(min_miles: Decimal | None, max_miles: Decimal | None) -> str:
    """Same wording as the carriers table."""
    if min_miles is None:
        return "Sınırsız" if max_miles is None else f"≤ {fmt_miles(max_miles)} mil"
    if max_miles is None:
        return f"≥ {fmt_miles(min_miles)} mil"
    return f"{fmt_miles(min_miles)}–{fmt_miles(max_miles)} mil"


def _distance_text(min_miles: Decimal | None, max_miles: Decimal | None) -> str:
    if min_miles is None:
        if max_miles is None:
            return "Mesafe sınırı yok: her uzunluktaki rotaya teklif verebilir."
        return f"En fazla {fmt_miles(max_miles)} millik rotaları taşır; daha uzun siparişlerde uygun sayılmaz."
    if max_miles is None:
        return f"En az {fmt_miles(min_miles)} millik rotaları taşır; daha kısa siparişlerde uygun sayılmaz."
    return f"{fmt_miles(min_miles)}–{fmt_miles(max_miles)} mil arasındaki rotaları taşır; dışında uygun sayılmaz."


def turkish_list(items: list[str]) -> str:
    """'20', '40', '45' -> '20, 40 ve 45'."""
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " ve " + items[-1]


def card(carrier: Carrier) -> dict[str, Any]:
    """Everything the page shows about one carrier, as JSON-safe values (no Decimal, no frozenset)."""
    sizes = [str(s) for s in sorted(carrier.container_sizes)]
    cargo = sorted(carrier.cargo_types)
    hazardous = _HAZARDOUS in carrier.cargo_types
    distance = distance_range(carrier.min_miles, carrier.max_miles)
    rate = f"{fmt_rate(carrier.rate_per_mile)} / mil"
    badges = [t.upper() for t in cargo if t != _HAZARDOUS]
    size_mark = " · ".join(sizes) + " FT"
    door_lines = [
        carrier.name,
        f"{carrier.hq_city} merkezli",
        "Mesafe sınırsız" if distance == "Sınırsız" else f"Mesafe {distance}",
    ]
    door_width = DOOR_SIZE[0] - 16
    cargo_text = f"Kabul ettiği yük tipleri: {turkish_list(cargo)}." + (
        " Tehlikeli yük (Hazardous) taşıyabilir." if hazardous else " Tehlikeli yük (Hazardous) taşımaz."
    )
    return {
        "id": carrier.id,
        "name": carrier.name,
        "hq": carrier.hq_city,
        "accent": accent(carrier.name),
        "font": lettering_size(carrier.name),
        "line": f"{carrier.hq_city} merkezli · {turkish_list(sizes)} ft · {turkish_list(cargo)}",
        "note": carrier.description,
        "hazardous": hazardous,
        # The markings on the truck (see the module docstring for where each one sits).
        "rate_line": rate,
        "size_mark": size_mark,
        "size_font": line_size(size_mark, SIZE_BOX[2], 30),
        "cargo_badges": badges,
        "badge_font": badge_size(badges, hazardous),
        "door": [
            {"text": text, "font": line_size(text, door_width, largest)}
            for text, largest in zip(door_lines, (60, 32, 32), strict=True)
        ],
        "facets": [
            {
                "key": "rate",
                "label": "Ücret",
                "value": rate,
                "text": "Teklifte toplam ücret, rotanın mili ile bu birim ücretin çarpımıdır.",
            },
            {
                "key": "distance",
                "label": "Mesafe",
                "value": distance,
                "text": _distance_text(carrier.min_miles, carrier.max_miles),
            },
            {
                "key": "equipment",
                "label": "Ekipman",
                "value": " · ".join(sizes) + " ft",
                "text": f"{turkish_list(sizes)} ft konteyner taşır. Sipariş bu ölçülerden biri değilse uygun sayılmaz.",
            },
            {"key": "cargo", "label": "Yük tipleri", "value": " · ".join(cargo), "text": cargo_text},
        ],
    }


def page_data(carriers: list[Carrier]) -> dict[str, Any]:
    """The JSON block the page script reads: carriers in display order plus the image geometry and cameras."""
    return {
        "carriers": [card(c) for c in carriers],
        "truck": {"width": TRUCK.width, "height": TRUCK.height, "origin": list(TRUCK_ORIGIN)},
        "scene": {"width": SCENE.width, "height": SCENE.height},
        "cameras": {key: {"box": list(cam.box), "zoom": cam.zoom} for key, cam in CAMERAS.items()},
    }
