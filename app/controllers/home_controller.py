"""Home page: the carriers as a truck showroom. Reads the carrier list only, so it never calls Jev or ORS.

`/` opens on the first carrier, `/a-logistics` on that one; the address follows the centre truck. The `/{slug}`
page is registered on the app itself, after every other route (`register_carrier_pages`), and is the only public
route besides the allowlist in app/auth.py (`PUBLIC_ROUTE`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth import PUBLIC_ROUTE
from app.dependencies import get_carrier_service
from app.services.carrier_service import CarrierService
from app.views import templates
from app.views.showroom import MARKING_STYLES, SCENE, TRUCK, card, page_data, unique_slugs

router = APIRouter(include_in_schema=False)

Service = Annotated[CarrierService, Depends(get_carrier_service)]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, service: Service) -> Response:
    return _showroom(request, service, slug=None)


def carrier_page(slug: str, request: Request, service: Service) -> Response:
    """One carrier in the centre; an unknown name (a deleted carrier, a typo) goes to the showroom's start."""
    return _showroom(request, service, slug=slug.lower())


def register_carrier_pages(app: FastAPI) -> None:
    """`/{slug}` catches every one-segment path, so it is added last, on the app, where auth can recognise it."""
    app.add_api_route(
        "/{slug}",
        carrier_page,
        methods=["GET"],
        name=PUBLIC_ROUTE,
        response_class=HTMLResponse,
        include_in_schema=False,
    )


def _showroom(request: Request, service: Service, slug: str | None) -> Response:
    carriers = service.list()
    start = 0
    if slug is not None:
        slugs = unique_slugs(carriers)
        if slug not in slugs:
            return RedirectResponse("/", status_code=303)
        start = slugs.index(slug)
    context = {
        "cards": [card(c) for c in carriers],
        "start": start,
        "data": {**page_data(carriers), "start": start},
        "truck": TRUCK,
        "scene": SCENE,
        "styles": MARKING_STYLES,
    }
    return templates.TemplateResponse(request, "home/index.html", context)
