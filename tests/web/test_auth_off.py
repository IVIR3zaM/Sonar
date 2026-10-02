"""Without sign-in settings the app is exactly the local, unauthenticated one (SPEC §13 Sign-in)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from sonar.web.app import create_app
from tests.html import soup
from tests.seed import seed


def _app(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    return create_app(db_path)


def test_no_session_middleware_without_auth(tmp_path):
    app = _app(tmp_path)

    assert all(middleware.cls is not SessionMiddleware for middleware in app.user_middleware)


def test_no_auth_routes_without_auth(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/auth/login")

    assert response.status_code == 404


def test_pages_open_without_a_cookie_and_show_no_sign_out(tmp_path):
    with TestClient(_app(tmp_path), follow_redirects=False) as client:
        response = client.get("/")

    assert response.status_code == 200
    page = soup(response)
    assert page.select_one("#sign-out") is None
    assert page.select_one("#signed-in-email") is None
