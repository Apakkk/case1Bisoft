"""City suggestions as JSON: the same CityService as the city inputs on the admin screen."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_city_service
from app.schemas.city import CitySuggestionsOut
from app.services.city_service import DEFAULT_LIMIT, MAX_LIMIT, CityService

router = APIRouter(prefix="/api/v1/cities", tags=["cities"])


@router.get("", response_model=CitySuggestionsOut)
def suggest_cities(
    service: Annotated[CityService, Depends(get_city_service)],
    q: Annotated[str, Query(max_length=100, description="What the user typed so far, any case")] = "",
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> CitySuggestionsOut:
    """US cities (never districts or streets) starting with `q`; OpenRouteService is asked only if needed."""
    return CitySuggestionsOut.from_suggestions(service.suggest(q, limit))
