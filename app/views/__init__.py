"""MVC View layer: Jinja2 templates rendered by the admin controllers (HTMX for partial updates)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.selection.formatting import fmt_miles, fmt_money, fmt_rate

VIEWS_DIR = Path(__file__).parent
STATIC_DIR = VIEWS_DIR.parent / "static"

templates = Jinja2Templates(directory=VIEWS_DIR / "templates")
templates.env.filters.update(money=fmt_money, miles=fmt_miles, rate=fmt_rate)
