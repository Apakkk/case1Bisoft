"""Login page and logout. The middleware in app/auth.py sends every unauthenticated page here."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth import COOKIE_NAME, LOGIN_PATH, SESSION_SECONDS, get_auth, safe_next
from app.views import templates

router = APIRouter(include_in_schema=False)


def _login_page(request: Request, next_path: str, email: str = "", error: str | None = None) -> Response:
    context = {"next": next_path, "email": email, "error": error}
    return templates.TemplateResponse(request, "auth/login.html", context, status_code=401 if error else 200)


@router.get(LOGIN_PATH, response_class=HTMLResponse)
def login_form(request: Request, next: str = "/") -> Response:
    target = safe_next(next)
    if get_auth(request).is_valid(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(target, status_code=303)
    return _login_page(request, target)


@router.post(LOGIN_PATH, response_class=HTMLResponse)
def login(
    request: Request,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
) -> Response:
    target = safe_next(next)
    auth = get_auth(request)
    if not auth.check(email, password):
        return _login_page(request, target, email=email.strip(), error="E-posta veya şifre hatalı.")
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(COOKIE_NAME, auth.issue(), max_age=SESSION_SECONDS, path="/", httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout() -> Response:
    response = RedirectResponse(LOGIN_PATH, status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return response
