"""Suggestion list under the city inputs (fetched by static/city-autocomplete.js, rendered server-side)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response

from app.dependencies import get_city_service
from app.services.city_service import CityService
from app.views import templates

router = APIRouter(prefix="/admin", include_in_schema=False)


@router.get("/cities/suggest", response_class=HTMLResponse)
def city_suggestions(
    request: Request,
    service: Annotated[CityService, Depends(get_city_service)],
    q: Annotated[str, Query(max_length=100)] = "",
) -> Response:
    return templates.TemplateResponse(request, "cities/_suggestions.html", {"result": service.suggest(q)})
