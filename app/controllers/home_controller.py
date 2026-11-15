"""Home page: the carriers as a truck showroom. Reads the carrier list only, so it never calls Jev or ORS."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.dependencies import get_carrier_service
from app.services.carrier_service import CarrierService
from app.views import templates
from app.views.showroom import MARKING_STYLES, SCENE, TRUCK, card, page_data

router = APIRouter(include_in_schema=False)

Service = Annotated[CarrierService, Depends(get_carrier_service)]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, service: Service) -> Response:
    carriers = service.list()
    context = {
        "cards": [card(c) for c in carriers],
        "data": page_data(carriers),
        "truck": TRUCK,
        "scene": SCENE,
        "styles": MARKING_STYLES,
    }
    return templates.TemplateResponse(request, "home/index.html", context)
