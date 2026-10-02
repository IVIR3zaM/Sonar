"""Google sign-in gate and pages (SPEC §13 Sign-in), with a fake Google client."""

from __future__ import annotations

import json
from base64 import b64decode
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from authlib.integrations.starlette_client import OAuthError
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from sonar.auth import store as auth_store
from sonar.auth.settings import AuthSettings
from sonar.db import connect
from sonar.web.app import create_app
from tests.html import soup, text
from tests.seed import seed
from tests.web.fake_google import FakeGoogle

AUTH = AuthSettings(
    google_client_id="client-id",
    google_client_secret="client-secret",
    session_secret="session-secret",
    base_url="http://testserver",
)


def _client(tmp_path: Path, google: FakeGoogle | None = None, auth: AuthSettings = AUTH):
    db_path = tmp_path / "t.db"
    seed(db_path)
    app = create_app(db_path, auth=auth, google=google or FakeGoogle())
    return TestClient(app, follow_redirects=False)


def test_signed_out_page_redirects_to_login(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/")

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


def _allow(tmp_path: Path, email: str) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        auth_store.allow_email(conn, email, datetime(2026, 1, 1, tzinfo=UTC))
    finally:
        conn.close()


def _revoke(tmp_path: Path, email: str) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        auth_store.revoke_email(conn, email)
    finally:
        conn.close()


def _sign_in(client: TestClient, google: FakeGoogle, email: str, verified: bool | None = True):
    google.signs_in(email, email_verified=verified)
    client.get("/auth/google")
    return client.get("/auth/callback")


def _session(client: TestClient) -> dict:
    cookie = client.cookies.get("sonar_session")
    if cookie is None:
        return {}
    data = TimestampSigner(AUTH.session_secret).unsign(cookie.encode())
    return json.loads(b64decode(data))


def test_signed_out_api_answers_401_json(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/categories")

    assert response.status_code == 401
    assert "error" in response.json()


def test_static_files_stay_public(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/static/sonar.css")

    assert response.status_code == 200


def test_login_page_offers_google_sign_in(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/auth/login")

    assert response.status_code == 200
    page = soup(response)
    button = page.select_one("#google-sign-in")
    assert button is not None
    assert button["href"] == "/auth/google"


def test_login_page_is_bare(tmp_path):
    with _client(tmp_path) as client:
        page = soup(client.get("/auth/login"))

    assert page.select_one("nav") is None
    assert page.select_one("#nav-drawer") is None
    assert page.select_one("#nav-open") is None
    assert page.select("[hx-get]") == []


def test_google_redirect_uses_the_base_url_callback(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        response = client.get("/auth/google")

    assert response.status_code == 302
    assert google.redirect_uris == ["http://testserver/auth/callback"]


def test_allowed_verified_email_signs_in(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        callback = _sign_in(client, google, "owner@example.com")
        home = client.get("/")
        api = client.get("/api/categories")

    assert callback.status_code == 302
    assert callback.headers["location"] == "/"
    assert home.status_code == 200
    assert api.status_code == 200


def test_session_holds_only_the_email_after_callback(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        client.get("/auth/google")
        assert _session(client) != {}
        google.signs_in("owner@example.com")
        client.get("/auth/callback")

        assert _session(client) == {"email": "owner@example.com"}


def test_signed_in_shell_shows_the_email_and_sign_out(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        _sign_in(client, google, "owner@example.com")
        page = soup(client.get("/"))

    assert text(page.select_one("#signed-in-email")) == "owner@example.com"
    assert page.select_one("#sign-out")["href"] == "/auth/logout"


@pytest.mark.parametrize("verified", [False, None])
def test_unverified_email_is_not_allowed_and_keeps_no_session(tmp_path, verified):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        callback = _sign_in(client, google, "owner@example.com", verified=verified)
        home = client.get("/")

        assert _session(client) == {}

    assert callback.status_code == 403
    assert soup(callback).select_one("#not-allowed") is not None
    assert home.status_code == 302
    assert home.headers["location"] == "/auth/login"


def test_unlisted_email_gets_the_not_allowed_page(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _sign_in(client, google, "stranger@example.com")
        home = client.get("/")
        api = client.get("/api/categories")

    assert home.status_code == 403
    page = soup(home)
    assert "stranger@example.com" in text(page.select_one("#not-allowed"))
    assert page.select_one("#sign-out")["href"] == "/auth/logout"
    assert page.select_one("nav") is None
    assert page.select("[hx-get]") == []
    assert api.status_code == 403
    assert "error" in api.json()


def test_revoking_an_email_bites_on_the_next_request(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        _sign_in(client, google, "owner@example.com")
        before = client.get("/")
        _revoke(tmp_path, "owner@example.com")
        after = client.get("/")

    assert before.status_code == 200
    assert after.status_code == 403


def test_logout_signs_out(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        _sign_in(client, google, "owner@example.com")
        logout = client.get("/auth/logout")
        home = client.get("/")

    assert logout.status_code == 302
    assert logout.headers["location"] == "/auth/login"
    assert home.status_code == 302
    assert home.headers["location"] == "/auth/login"


def test_oauth_error_shows_the_sign_in_page_with_an_error(tmp_path):
    google = FakeGoogle()
    google.error = OAuthError(error="access_denied")
    with _client(tmp_path, google) as client:
        client.get("/auth/google")
        response = client.get("/auth/callback")

    assert response.status_code == 400
    page = soup(response)
    assert page.select_one("#login-error") is not None
    assert page.select_one("#google-sign-in") is not None


def _session_cookie_header(response) -> str:
    headers = [h for h in response.headers.get_list("set-cookie") if "sonar_session=" in h]
    assert len(headers) == 1
    return headers[0].lower()


def test_session_cookie_flags_over_http(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        callback = _sign_in(client, google, "owner@example.com")

    header = _session_cookie_header(callback)
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "max-age=1209600" in header
    assert "secure" not in header


def test_session_cookie_is_secure_with_an_https_base_url(tmp_path):
    google = FakeGoogle()
    https = replace(AUTH, base_url="https://sonar.example.com")
    with _client(tmp_path, google, auth=https) as client:
        _allow(tmp_path, "owner@example.com")
        google.signs_in("owner@example.com")
        callback = client.get("/auth/callback")

    header = _session_cookie_header(callback)
    assert "secure" in header
    assert "httponly" in header


def test_default_google_client_needs_no_network_to_start(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    with TestClient(create_app(db_path, auth=AUTH), follow_redirects=False) as client:
        response = client.get("/auth/login")

    assert response.status_code == 200
