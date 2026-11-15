from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_quote_service
from app.schemas.quote import QuoteRequest, QuoteResponse
from app.services.quote_service import QuoteService

router = APIRouter(prefix="/api/v1", tags=["quotes"])


@router.post("/quotes", response_model=QuoteResponse)
def create_quote(request: QuoteRequest, service: Annotated[QuoteService, Depends(get_quote_service)]) -> QuoteResponse:
    """Select a carrier for an order. Business outcomes (incl. "no carrier") are 200 with a `status`."""
    return QuoteResponse.from_quote(service.quote(request))
