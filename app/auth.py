"""Login: one middleware refuses every request without a valid session, apart from a short allowlist.

Browsers log in on /login and get a signed cookie (stdlib HMAC, no server-side store). API clients may send
the same credentials as HTTP Basic instead (curl -u, scripts/run_case_orders.py). New routes are protected
without doing anything: the allowlist is the only way out.
"""

import base64
import binascii
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.config import Settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "session"
SESSION_SECONDS = 8 * 60 * 60
LOGIN_PATH = "/login"
PUBLIC_PATHS = frozenset({"/health", LOGIN_PATH, "/logout"})  # /health: the Docker healthcheck has no login
PUBLIC_PREFIXES = ("/static/",)
API_PREFIX = "/api/"


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True, slots=True)
class Auth:
    email: str
    password: str
    secret: bytes

    @classmethod
    def from_settings(cls, settings: Settings) -> "Auth":
        if settings.session_secret is not None:
            secret = settings.session_secret.get_secret_value().encode()
        else:
            logger.warning("SESSION_SECRET is not set: using a random key, so every restart logs everyone out")
            secret = secrets.token_bytes(32)
        return cls(settings.admin_email.strip().lower(), settings.admin_password.get_secret_value(), secret)

    def check(self, email: str, password: str) -> bool:
        """Constant-time comparison of both fields; the e-mail ignores case and surrounding spaces."""
        email_ok = secrets.compare_digest(email.strip().lower().encode(), self.email.encode())
        password_ok = secrets.compare_digest(password.encode(), self.password.encode())
        return email_ok & password_ok

    def issue(self, now: float | None = None) -> str:
        """Cookie value: base64(email|expiry).hmac. Changing the e-mail or the secret invalidates old cookies."""
        expires = int((time.time() if now is None else now) + SESSION_SECONDS)
        payload = _b64encode(f"{self.email}|{expires}".encode())
        return f"{payload}.{self._sign(payload)}"

    def is_valid(self, token: str | None, now: float | None = None) -> bool:
        if not token or token.count(".") != 1:
            return False
        payload, signature = token.split(".")
        if not secrets.compare_digest(signature.encode(), self._sign(payload).encode()):
            return False
        try:
            email, _, expires = _b64decode(payload).decode().rpartition("|")
            return email == self.email and int(expires) > (time.time() if now is None else now)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False

    def basic_ok(self, header: str | None) -> bool:
        """`Authorization: Basic base64(email:password)` with the same account."""
        scheme, _, encoded = (header or "").partition(" ")
        if scheme.lower() != "basic" or not encoded:
            return False
        try:
            email, sep, password = base64.b64decode(encoded.strip(), validate=True).decode().partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return False
        return bool(sep) and self.check(email, password)

    def _sign(self, payload: str) -> str:
        return _b64encode(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def safe_next(value: str | None) -> str:
    """Only a path on this site: '/admin/quote?x=1' yes; '//evil.com', 'https://…', '/\\evil' no (open redirect)."""
    if not value or not value.startswith("/") or value.startswith(("//", "/\\")):
        return "/"
    if any(c == "\\" or ord(c) < 0x20 or ord(c) == 0x7F for c in value) or urlsplit(value).netloc:
        return "/"
    return "/" if urlsplit(value).path in (LOGIN_PATH, "/logout") else value


def login_url(next_path: str) -> str:
    target = safe_next(next_path)
    return LOGIN_PATH if target == "/" else f"{LOGIN_PATH}?{urlencode({'next': target})}"


def _refuse(request: Request) -> Response:
    """JSON for the API, HX-Redirect for HTMX swaps, a bare 401 for scripts' fetch(), a redirect for navigation."""
    if request.url.path.startswith(API_PREFIX):
        return JSONResponse(
            status_code=401,
            content={"error": "UNAUTHORIZED", "detail": "Log in on /login or send HTTP Basic credentials."},
            headers={"WWW-Authenticate": 'Basic realm="Carrier Selection"'},
        )
    if request.headers.get("HX-Request") == "true":
        # The swap target (#result, #editor) must not receive the login page: send the whole tab there.
        current = urlsplit(request.headers.get("HX-Current-URL", ""))
        page = current.path + (f"?{current.query}" if current.query else "")
        return Response(status_code=401, headers={"HX-Redirect": login_url(page)})
    if request.headers.get("Sec-Fetch-Mode", "navigate") != "navigate":
        # A browser fetch() (city suggestions) would follow a redirect and insert the login page into the list.
        return Response("Login required", status_code=401, media_type="text/plain")
    query = request.url.query
    return RedirectResponse(login_url(request.url.path + (f"?{query}" if query else "")), status_code=303)


def install_auth(app: FastAPI, auth: Auth) -> None:
    app.state.auth = auth

    @app.middleware("http")
    async def require_login(request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if (
            is_public(path)
            or auth.is_valid(request.cookies.get(COOKIE_NAME))
            or (path.startswith(API_PREFIX) and auth.basic_ok(request.headers.get("Authorization")))
        ):
            return await call_next(request)
        return _refuse(request)


def get_auth(request: Request) -> Auth:
    auth: Auth = request.app.state.auth
    return auth
