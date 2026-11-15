"""MVC View layer: Jinja2 templates rendered by the admin controllers (HTMX for partial updates)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.selection.formatting import fmt_miles, fmt_money, fmt_rate

VIEWS_DIR = Path(__file__).parent
STATIC_DIR = VIEWS_DIR.parent / "static"

# DistanceSource values (API codes) -> what the screen says.
DISTANCE_SOURCES = {
    "same_city": "aynı şehir",
    "case_table": "case tablosu",
    "cache": "harita servisi, kayıtlı",
    "ors": "harita servisi",
    "haversine": "kuş uçuşu × katsayı",
}


def distance_source(code: str | None) -> str:
    return DISTANCE_SOURCES.get(code or "", code or "")


def place(name: str, state: str = "") -> str:
    """'Paris', 'TX' -> 'Paris, TX': the state shows which city a name was resolved to."""
    return f"{name}, {state}" if state else name


templates = Jinja2Templates(directory=VIEWS_DIR / "templates")
templates.env.filters.update(
    money=fmt_money, miles=fmt_miles, rate=fmt_rate, distance_source=distance_source, place=place
)
