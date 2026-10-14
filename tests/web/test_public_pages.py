"""The public /privacy and /terms pages (SPEC §13 Sign-in): open even with sign-in on."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.auth.settings import AuthSettings
from sonar.banking.settings import BankSettings
from sonar.web.app import create_app
from tests.html import soup, text
from tests.seed import seed
from tests.web.fake_bank import FakeBank
from tests.web.fake_google import FakeGoogle

AUTH = AuthSettings(
    google_client_id="client-id",
    google_client_secret="client-secret",
    session_secret="session-secret",
    base_url="http://testserver",
)
BANK = BankSettings(
    app_id="app-id",
    key_path=Path("unused.pem"),
    redirect_url="http://testserver/bank/callback",
)
LOGIN = "/auth/login"


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "t.db"
    seed(db_path)
    app = create_app(
        db_path,
        today=lambda: date(2026, 10, 14),
        now=lambda: datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
        auth=AUTH,
        google=FakeGoogle(),
        bank=BANK,
        bank_client=FakeBank(),
    )
    return TestClient(app, follow_redirects=False)


def test_public_privacy_page_is_open_and_bare(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/privacy")

    assert response.status_code == 200
    page = soup(response)
    body = text(page.select_one("#privacy"))
    assert "third party" in body
    assert "deleting that database" in body
    _assert_bare(page)


def test_public_terms_page_is_open_and_bare(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/terms")

    assert response.status_code == 200
    page = soup(response)
    assert "not offered to the public" in text(page.select_one("#terms"))
    _assert_bare(page)


def _assert_bare(page) -> None:
    assert page.select_one("nav") is None
    assert page.select("[hx-get]") == []
    assert page.select_one("#bank-banner-slot") is None


def _filled(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_gated_every_other_route_still_needs_sign_in(tmp_path):
    with _client(tmp_path) as client:
        # OpenAPI lists every APIRoute with its full path; nothing in the app hides from it.
        checked: set[str] = set()
        for route_path, operations in client.app.openapi()["paths"].items():
            path = _filled(route_path)
            if path.startswith("/auth/") or path in {"/privacy", "/terms"}:
                continue
            for method in operations:
                response = client.request(method.upper(), path)
                checked.add(path)
                if path.startswith("/api"):
                    assert response.status_code == 401, (method, path)
                    assert "error" in response.json(), (method, path)
                else:
                    assert response.status_code == 302, (method, path)
                    assert response.headers["location"] == LOGIN, (method, path)

    assert {"/", "/settings", "/api/rules", "/bank/banner"} <= checked


@pytest.mark.parametrize("path", ["/privacy/", "/privacy/x", "/privacyx", "/terms.html", "/Terms"])
def test_lookalike_paths_stay_gated(tmp_path, path):
    with _client(tmp_path) as client:
        response = client.get(path)

    assert response.status_code == 302
    assert response.headers["location"] == LOGIN
