"""Admin quote form: the same QuoteService as POST /api/v1/quotes, rendered as a result card."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from app.clients.distance.chain import UnknownLocationError
from app.dependencies import get_carrier_service, get_quote_service, get_rules
from app.schemas.quote import QuoteRequest, QuoteResponse
from app.selection.rules import FINAL_TIE_BREAKER, RuleSet
from app.services.carrier_service import CarrierService
from app.services.quote_service import InvalidOrderError, QuoteService
from app.services.rules_service import criterion_option
from app.views import templates

router = APIRouter(prefix="/admin", include_in_schema=False)


@router.get("/quote", response_class=HTMLResponse)
def quote_page(
    request: Request,
    rules: Annotated[RuleSet, Depends(get_rules)],
    carriers: Annotated[CarrierService, Depends(get_carrier_service)],
) -> Response:
    ranking = [criterion_option(name).label for name in rules.ranking if name != FINAL_TIE_BREAKER]
    context = {"catalog": rules, "sizes": carriers.container_sizes(), "ranking": ranking}
    return templates.TemplateResponse(request, "quote/index.html", context)


@router.post("/quote", response_class=HTMLResponse)
def run_quote(
    request: Request,
    service: Annotated[QuoteService, Depends(get_quote_service)],
    origin: Annotated[str, Form()] = "",
    destination: Annotated[str, Form()] = "",
    container_size: Annotated[str, Form()] = "",
    cargo_type: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    confirm_mismatch: Annotated[str, Form()] = "",  # the checkbox on a needs_confirmation result
) -> Response:
    try:
        order = QuoteRequest.model_validate(
            {
                "origin": origin,
                "destination": destination,
                "container_size": container_size or None,
                "cargo_type": cargo_type or None,
                "description": description.strip() or None,
                "confirm_mismatch": confirm_mismatch == "true",
            }
        )
        quote = QuoteResponse.from_quote(service.quote(order))
    except ValidationError as error:
        return _error(request, "INVALID_INPUT", "; ".join(str(e["msg"]) for e in error.errors(include_url=False)))
    except InvalidOrderError as error:
        return _error(request, "INVALID_ORDER", str(error))
    except UnknownLocationError as error:
        return _error(request, "UNKNOWN_LOCATION", error.message)
    return templates.TemplateResponse(request, "quote/_result.html", {"q": quote, "error": None})


def _error(request: Request, code: str, detail: str) -> Response:
    context = {"q": None, "error": {"code": code, "detail": detail}}
    return templates.TemplateResponse(request, "quote/_result.html", context)
