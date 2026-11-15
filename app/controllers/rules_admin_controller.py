"""Admin rules page: reorder the ranking criteria and save them to rules.yaml (HTMX partial updates).

Editing happens on a draft carried in the form (no server state); only "Kaydet" writes the file.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.dependencies import get_rules_service
from app.selection.rules import RulesError
from app.services.rules_service import RulesService, available_criteria, criterion_option, edit_ranking
from app.views import templates

router = APIRouter(prefix="/admin", include_in_schema=False)

Service = Annotated[RulesService, Depends(get_rules_service)]
Ranking = Annotated[list[str] | None, Form()]


@router.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request, service: Service) -> Response:
    saved = service.active_ranking()
    context = {"rules": service.current(), "editor": _editor(saved, saved)}
    return templates.TemplateResponse(request, "rules/index.html", context)


@router.post("/rules/ranking/draft", response_class=HTMLResponse)
def edit_draft(
    request: Request, service: Service, ranking: Ranking = None, op: Annotated[str, Form()] = ""
) -> Response:
    saved = service.active_ranking()
    draft = edit_ranking(ranking or [], op, saved)
    return templates.TemplateResponse(request, "rules/_ranking.html", {"editor": _editor(draft, saved)})


@router.post("/rules/ranking", response_class=HTMLResponse)
def save_ranking(request: Request, service: Service, ranking: Ranking = None) -> Response:
    draft = edit_ranking(ranking or [], "", [])
    try:
        service.save_ranking(draft)
    except RulesError as error:
        editor = _editor(draft, service.active_ranking(), error=str(error))
    else:
        editor = _editor(
            draft, draft, message="Kaydedildi: config/rules.yaml güncellendi; sonraki teklifler bu sırayla."
        )
    return templates.TemplateResponse(request, "rules/_ranking.html", {"editor": editor})


def _editor(draft: list[str], saved: list[str], *, message: str | None = None, error: str | None = None) -> Any:
    return {
        "items": [criterion_option(key) for key in draft],
        "available": [criterion_option(key) for key in available_criteria(draft)],
        "dirty": draft != saved,
        "message": message,
        "error": error,
    }
