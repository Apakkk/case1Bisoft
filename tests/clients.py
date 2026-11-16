"""TestClient that has logged in through the real /login form, so tests go through the same middleware as users."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, Auth

# The account every test runs with (tests/conftest.py puts it in the environment, which outranks .env).
TEST_EMAIL = "admin@example.com"
TEST_PASSWORD = "test-password"


def logged_in(app: FastAPI) -> TestClient:
    client = TestClient(app)
    auth: Auth = app.state.auth
    response = client.post("/login", data={"email": auth.email, "password": auth.password}, follow_redirects=False)
    assert response.status_code == 303 and COOKIE_NAME in client.cookies, response.text
    return client
