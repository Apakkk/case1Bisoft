"""Login: every route outside the allowlist refuses anonymous requests; the cookie and HTTP Basic let you in."""

import base64
import re
from collections.abc import Iterable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.routing import BaseRoute, Route

from app.auth import COOKIE_NAME, PUBLIC_ROUTE, SESSION_SECONDS, Auth, is_public, safe_next
from app.config import Settings
from app.dependencies import get_carrier_service, get_rules
from app.main import create_app
from app.services.carrier_service import CarrierService
from tests.case_data import CASE_CARRIERS, default_rules
from tests.clients import TEST_EMAIL, TEST_PASSWORD, logged_in
from tests.fakes import InMemoryCarrierRepository, StaticRules, offline_distances

AUTH = Auth(TEST_EMAIL, TEST_PASSWORD, b"test-secret")


@pytest.fixture(autouse=True)
def default_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test account from tests/conftest.py; no .env, so its SESSION_SECRET or real account never leaks in."""
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(_env_file=None))


def app_with_carriers() -> FastAPI:
    app = create_app()
    repo, rules = InMemoryCarrierRepository(CASE_CARRIERS), StaticRules(default_rules())
    app.dependency_overrides[get_carrier_service] = lambda: CarrierService(repo, offline_distances(), rules)
    app.dependency_overrides[get_rules] = lambda: rules.get()
    return app


def basic(email: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{email}:{password}".encode()).decode()}


@pytest.fixture
def anonymous() -> TestClient:
    return TestClient(app_with_carriers(), follow_redirects=False)


# --- Default deny ---------------------------------------------------------------------------------------------------


def endpoints(routes: Iterable[BaseRoute], prefix: str = "") -> Iterator[tuple[str, set[str], str]]:
    """(path, methods, name) of every endpoint; included routers are kept nested in this FastAPI version, so recurse."""
    for route in routes:
        router = getattr(route, "original_router", None)
        if router is not None:
            yield from endpoints(router.routes, prefix + route.include_context.prefix)  # type: ignore[attr-defined]
        elif isinstance(route, APIRoute | Route):
            yield prefix + route.path, set(route.methods or {"GET"}), route.name


def test_every_route_outside_the_allowlist_refuses_anonymous_requests() -> None:
    app = create_app()
    client = TestClient(app, follow_redirects=False)
    checked: set[str] = set()
    for path, methods, name in endpoints(app.routes):
        if is_public(path) or name == PUBLIC_ROUTE:  # the carrier pages have their own tests below
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        for method in methods - {"HEAD"}:
            response = client.request(method, url)
            assert response.status_code in (401, 303), f"{method} {url} -> {response.status_code}"
            checked.add(url)
    expected = {"/docs", "/openapi.json", "/admin/quote", "/admin/rules", "/api/v1/quotes", "/api/v1/carriers/1"}
    assert expected <= checked
    assert len(checked) >= 19  # every route but the allowlist ("/" is public now)


def test_docs_and_the_schema_need_a_login(anonymous: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert anonymous.get(path).status_code == 303


def test_only_the_home_page_itself_is_public() -> None:
    assert is_public("/")
    assert not any(is_public(path) for path in ("/admin", "/admin/carriers", "/admin/quote", "/api/v1/carriers"))


def test_health_login_and_static_files_stay_open(anonymous: TestClient) -> None:
    assert anonymous.get("/health").status_code == 200  # the Docker healthcheck has no cookie
    assert anonymous.get("/login").status_code == 200
    assert anonymous.get("/static/pico.min.css").status_code == 200


# --- The three refusal shapes ---------------------------------------------------------------------------------------


def test_a_page_redirects_to_login_and_remembers_where_you_were(anonymous: TestClient) -> None:
    response = anonymous.get("/admin/quote?x=1")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fadmin%2Fquote%3Fx%3D1"


def test_the_api_answers_401_in_the_usual_error_shape(anonymous: TestClient) -> None:
    response = anonymous.post("/api/v1/quotes", json={})

    assert response.status_code == 401
    assert response.json()["error"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"].startswith("Basic")


def test_a_script_fetch_gets_a_bare_401_not_the_login_page(anonymous: TestClient) -> None:
    # city-autocomplete.js uses fetch(), which would follow a redirect and show the login form as suggestions.
    headers = {"Sec-Fetch-Mode": "cors", "Accept": "text/html"}

    response = anonymous.get("/admin/cities/suggest?q=mia", headers=headers)

    assert response.status_code == 401
    assert "location" not in response.headers and "<form" not in response.text


def test_browser_navigation_still_redirects(anonymous: TestClient) -> None:
    assert anonymous.get("/admin/rules", headers={"Sec-Fetch-Mode": "navigate"}).status_code == 303


def test_an_htmx_request_sends_the_whole_tab_to_login(anonymous: TestClient) -> None:
    headers = {"HX-Request": "true", "HX-Current-URL": "http://testserver/admin/carriers"}

    response = anonymous.get("/admin/carriers/new", headers=headers)

    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login?next=%2Fadmin%2Fcarriers"
    assert response.text == ""  # nothing is swapped into #editor


# --- Logging in and out ---------------------------------------------------------------------------------------------


def test_login_sets_a_protected_cookie_and_goes_back(anonymous: TestClient) -> None:
    form = {"email": " ADMIN@Example.com ", "password": TEST_PASSWORD, "next": "/admin/carriers"}

    response = anonymous.post("/login", data=form)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/carriers"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and f"max-age={SESSION_SECONDS}" in cookie
    assert anonymous.get("/admin/carriers").status_code == 200
    assert anonymous.get("/api/v1/carriers").status_code == 200


@pytest.mark.parametrize("email, password", [(TEST_EMAIL, "wrong"), ("other@example.com", TEST_PASSWORD), ("", "")])
def test_wrong_credentials_show_the_form_again(anonymous: TestClient, email: str, password: str) -> None:
    response = anonymous.post("/login", data={"email": email, "password": password, "next": "/admin/rules"})

    assert response.status_code == 401
    assert "E-posta veya şifre hatalı." in response.text
    assert 'name="next" value="/admin/rules"' in response.text
    assert COOKIE_NAME not in anonymous.cookies


def test_the_login_page_of_a_logged_in_user_goes_straight_on() -> None:
    client = logged_in(app_with_carriers())

    response = client.get("/login?next=/admin/quote", follow_redirects=False)

    assert response.status_code == 303 and response.headers["location"] == "/admin/quote"


def test_logout_clears_the_cookie() -> None:
    client = logged_in(app_with_carriers())

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303 and response.headers["location"] == "/"  # back to the public showroom
    assert COOKIE_NAME not in client.cookies
    assert client.get("/admin/carriers", follow_redirects=False).status_code == 303


def test_pages_have_a_logout_button() -> None:
    client = logged_in(app_with_carriers())
    for path in ("/", "/admin/carriers"):
        assert 'action="/logout"' in client.get(path).text


@pytest.mark.parametrize(
    "value, expected",
    [
        ("/admin/quote?x=1", "/admin/quote?x=1"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
        ("https://evil.example/", "/"),
        ("admin", "/"),
        ("/admin\r\nSet-Cookie: x", "/"),
        ("/login?next=/x", "/"),
        ("/logout", "/"),
        ("", "/"),
    ],
)
def test_next_stays_on_this_site(value: str, expected: str) -> None:
    assert safe_next(value) == expected


def test_an_outside_next_is_not_followed_after_login(anonymous: TestClient) -> None:
    response = anonymous.post("/login", data={"email": AUTH.email, "password": TEST_PASSWORD, "next": "//evil.example"})

    assert response.headers["location"] == "/"


# --- HTTP Basic for API clients -------------------------------------------------------------------------------------


def test_the_api_accepts_http_basic_with_the_same_account(anonymous: TestClient) -> None:
    assert anonymous.get("/api/v1/carriers", headers=basic(TEST_EMAIL, TEST_PASSWORD)).status_code == 200
    assert anonymous.get("/api/v1/carriers", headers=basic(TEST_EMAIL, "nope")).status_code == 401
    assert anonymous.get("/api/v1/carriers", headers={"Authorization": "Basic !!!"}).status_code == 401


def test_http_basic_does_not_open_the_pages(anonymous: TestClient) -> None:
    assert anonymous.get("/admin/carriers", headers=basic(TEST_EMAIL, TEST_PASSWORD)).status_code == 303


# --- The cookie itself ----------------------------------------------------------------------------------------------


def test_a_cookie_is_valid_until_it_expires() -> None:
    token = AUTH.issue(now=1_000)

    assert AUTH.is_valid(token, now=1_000 + SESSION_SECONDS - 1)
    assert not AUTH.is_valid(token, now=1_000 + SESSION_SECONDS)


def test_a_tampered_or_foreign_cookie_is_refused() -> None:
    token = AUTH.issue()
    payload, signature = token.split(".")
    forged_payload = base64.urlsafe_b64encode(f"{TEST_EMAIL}|99999999999".encode()).decode().rstrip("=")

    assert not AUTH.is_valid(f"{forged_payload}.{signature}")
    assert not AUTH.is_valid(f"{payload}.{signature[:-2]}xx")
    assert not Auth(AUTH.email, AUTH.password, b"another-secret").is_valid(token)
    assert not Auth("someone@else.com", AUTH.password, AUTH.secret).is_valid(token)
    for junk in ("", "abc", "a.b.c", "!!!.???"):
        assert not AUTH.is_valid(junk)


def test_settings_take_the_account_from_the_environment_and_a_random_key_when_none_is_set() -> None:
    settings = Settings(_env_file=None)

    first, second = Auth.from_settings(settings), Auth.from_settings(settings)

    assert first.check(TEST_EMAIL, TEST_PASSWORD)
    assert first.secret != second.secret
    fixed = Settings(_env_file=None, session_secret="s3cret")
    assert Auth.from_settings(fixed).secret == b"s3cret"


def test_the_account_is_required_and_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_EMAIL")
    monkeypatch.delenv("ADMIN_PASSWORD")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    assert {e["loc"][0] for e in error.value.errors()} == {"admin_email", "admin_password"}


# --- Public showroom, locked menu -----------------------------------------------------------------------------------

LOCKED = re.compile(r'<a href="/login\?next=%2Fadmin%2F(carriers|quote|rules)" class="locked" title="Giriş gerekli">')


def test_the_showroom_opens_without_a_login_and_locks_the_admin_links() -> None:
    response = TestClient(app_with_carriers(), follow_redirects=False).get("/")

    assert response.status_code == 200
    html = response.text
    assert sorted(LOCKED.findall(html)) == ["carriers", "quote", "rules"]
    assert '<a href="/login" class="login-link">Giriş</a>' in html
    assert 'action="/logout"' not in html
    # The showroom's own buttons are locked the same way.
    assert re.search(r'<a class="cta locked" href="/login\?next=%2Fadmin%2Fquote"[^>]*>.*Teklif al', html)


def test_a_locked_link_leads_through_the_login_to_its_page() -> None:
    client = TestClient(app_with_carriers(), follow_redirects=False)
    assert client.get("/admin/quote").headers["location"] == "/login?next=%2Fadmin%2Fquote"  # typed address

    response = client.post("/login", data={"email": TEST_EMAIL, "password": TEST_PASSWORD, "next": "/admin/quote"})

    assert response.status_code == 303 and response.headers["location"] == "/admin/quote"


def test_logged_in_the_menu_has_no_locks_and_marks_the_current_page() -> None:
    client = logged_in(app_with_carriers())

    home = client.get("/").text
    carriers = client.get("/admin/carriers").text

    assert "locked" not in home and "locked" not in carriers
    assert '<a href="/admin/carriers" aria-current="page">Firmalar</a>' in carriers
    assert '<a href="/admin/quote">Teklif</a>' in home and '<a class="cta" href="/admin/quote">Teklif al</a>' in home


def test_the_login_page_shows_the_locked_menu_without_a_second_login_button(anonymous: TestClient) -> None:
    html = anonymous.get("/login?next=/admin/rules").text

    assert sorted(LOCKED.findall(html)) == ["carriers", "quote", "rules"]
    assert 'class="login-link"' not in html


# --- Public carrier pages (/a-logistics) ----------------------------------------------------------------------------


def test_a_carrier_page_opens_without_a_login_on_that_carrier(anonymous: TestClient) -> None:
    response = anonymous.get("/m-logistics")

    assert response.status_code == 200
    html = response.text
    assert '<h1 class="hero-name" data-name>M-Logistics</h1>' in html
    assert "<span data-counter>03 / 04</span>" in html  # A, B, M, S
    assert '"start": 2' in html


def test_an_unknown_carrier_page_goes_to_the_showroom_not_to_the_login(anonymous: TestClient) -> None:
    for path in ("/yok-boyle-firma", "/M-LOGISTICS-X"):
        response = anonymous.get(path)
        assert (response.status_code, response.headers["location"]) == (303, "/"), path


def test_one_segment_app_routes_stay_locked_although_carrier_pages_are_public(anonymous: TestClient) -> None:
    for path in ("/docs", "/redoc", "/admin"):
        response = anonymous.get(path)
        assert response.status_code == 303 and response.headers["location"].startswith("/login"), path
    assert anonymous.post("/m-logistics").status_code in (401, 303, 405)  # only GET is public
