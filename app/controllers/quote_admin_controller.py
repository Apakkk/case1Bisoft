"""Admin quote form: the same QuoteService as POST /api/v1/quotes, rendered as a result card."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from app.clients.distance.chain import UnknownLocationError
from app.dependencies import get_quote_service, get_rules
from app.schemas.quote import QuoteRequest, QuoteResponse
from app.selection.rules import RuleSet
from app.services.quote_service import InvalidOrderError, QuoteService
from app.views import templates

router = APIRouter(prefix="/admin", include_in_schema=False)


@router.get("/quote", response_class=HTMLResponse)
def quote_page(request: Request, rules: Annotated[RuleSet, Depends(get_rules)]) -> Response:
    return templates.TemplateResponse(request, "quote/index.html", {"catalog": rules})


@router.post("/quote", response_class=HTMLResponse)
def run_quote(
    request: Request,
    service: Annotated[QuoteService, Depends(get_quote_service)],
    origin: Annotated[str, Form()] = "",
    destination: Annotated[str, Form()] = "",
    container_size: Annotated[str, Form()] = "",
    cargo_type: Annotated[str, Form()] = "",
    cargo_description: Annotated[str, Form()] = "",
) -> Response:
    try:
        order = QuoteRequest.model_validate(
            {
                "origin": origin,
                "destination": destination,
                "container_size": container_size or None,
                "cargo_type": cargo_type or None,
                "cargo_description": cargo_description.strip() or None,
            }
        )
        quote = QuoteResponse.from_quote(service.quote(order))
    except ValidationError as error:
        return _error(request, "INVALID_INPUT", "; ".join(str(e["msg"]) for e in error.errors(include_url=False)))
    except InvalidOrderError as error:
        return _error(request, "INVALID_ORDER", str(error))
    except UnknownLocationError as error:
        return _error(request, "UNKNOWN_LOCATION", f"Konum bulunamadı: {error.city}")
    return templates.TemplateResponse(request, "quote/_result.html", {"q": quote, "error": None})


def _error(request: Request, code: str, detail: str) -> Response:
    context = {"q": None, "error": {"code": code, "detail": detail}}
    return templates.TemplateResponse(request, "quote/_result.html", context)
