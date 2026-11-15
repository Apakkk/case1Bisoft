"""Admin screen for carriers (MVC controller): server-rendered pages, HTMX partial updates."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.dependencies import get_carrier_service, get_rules
from app.models.carrier import Carrier, NoteStatus
from app.repositories.carrier_repository import DuplicateCarrierError, InvalidCarrierError
from app.selection.rules import RuleSet
from app.services.carrier_service import CarrierService, CarrierValidationError
from app.views import templates
from app.views.forms import CarrierForm, form_errors, read_carrier_form

router = APIRouter(prefix="/admin", include_in_schema=False)

Service = Annotated[CarrierService, Depends(get_carrier_service)]
Rules = Annotated[RuleSet, Depends(get_rules)]
FormData = Annotated[CarrierForm, Depends(read_carrier_form)]


@router.get("")
def admin_home() -> RedirectResponse:
    return RedirectResponse("/admin/carriers")


@router.get("/carriers", response_class=HTMLResponse)
def carriers_page(request: Request, service: Service) -> Response:
    return templates.TemplateResponse(request, "carriers/index.html", {"carriers": service.list(), "oob": False})


@router.get("/carriers/new", response_class=HTMLResponse)
def new_form(request: Request, rules: Rules) -> Response:
    return _form(request, rules, CarrierForm(), carrier_id=None)


@router.get("/carriers/editor/close", response_class=HTMLResponse)
def close_editor() -> HTMLResponse:
    return HTMLResponse("")


@router.get("/carriers/{carrier_id}/edit", response_class=HTMLResponse)
def edit_form(carrier_id: int, request: Request, service: Service, rules: Rules) -> Response:
    return _form(request, rules, CarrierForm.from_carrier(service.get(carrier_id)), carrier_id=carrier_id)


@router.post("/carriers", response_class=HTMLResponse)
def create_carrier(request: Request, form: FormData, service: Service, rules: Rules) -> Response:
    return _save(request, form, service, rules, carrier_id=None)


@router.put("/carriers/{carrier_id}", response_class=HTMLResponse)
def update_carrier(carrier_id: int, request: Request, form: FormData, service: Service, rules: Rules) -> Response:
    return _save(request, form, service, rules, carrier_id=carrier_id)


@router.delete("/carriers/{carrier_id}", response_class=HTMLResponse)
def delete_carrier(carrier_id: int, service: Service) -> HTMLResponse:
    service.delete(carrier_id)
    return HTMLResponse("")  # HTMX swaps the row out


def _save(
    request: Request, form: CarrierForm, service: CarrierService, rules: RuleSet, carrier_id: int | None
) -> Response:
    try:
        data = form.to_input()
        carrier = service.create(data) if carrier_id is None else service.update(carrier_id, data)
    except ValidationError as error:
        return _form(request, rules, form, carrier_id, form_errors(error))
    except CarrierValidationError as error:
        return _form(request, rules, form, carrier_id, error.screen_errors)
    except DuplicateCarrierError:
        return _form(request, rules, form, carrier_id, {"name": "Bu isimde bir firma zaten var."})
    except InvalidCarrierError as error:
        return _form(request, rules, form, carrier_id, {"_": str(error)})
    context = {"message": _saved_message(carrier), "carriers": service.list(), "oob": True}
    return templates.TemplateResponse(request, "carriers/_saved.html", context)


def _form(
    request: Request,
    rules: RuleSet,
    form: CarrierForm,
    carrier_id: int | None,
    errors: dict[str, str] | None = None,
) -> Response:
    # Validation errors are rendered with 200 so HTMX swaps the form back in with the messages.
    context = {"form": form, "carrier_id": carrier_id, "errors": errors or {}, "catalog": rules}
    return templates.TemplateResponse(request, "carriers/_form.html", context)


def _saved_message(carrier: Carrier) -> str:
    message = f"{carrier.name} kaydedildi."
    if carrier.description and carrier.note_status is NoteStatus.CONSTRAINT:
        message += (
            f" Jev: açıklama kısıt içeriyor (olasılık {carrier.note_confidence:.2f}); siparişlerde kontrol edilecek."
        )
    elif carrier.description and carrier.note_status is NoteStatus.UNCHECKED:
        message += " Jev'e ulaşılamadı; açıklama siparişlerde kontrol edilecek."
    elif carrier.description:
        message += " Jev: açıklama kısıt içermiyor."
    return message
