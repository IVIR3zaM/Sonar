"""The optional API bearer token (SPEC §13 Sign-in): /api/* only, never pages."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.auth import store as auth_store
from sonar.auth.settings import AuthSettings
from sonar.db import connect
from sonar.web.app import create_app
from tests.seed import seed
from tests.web.fake_google import FakeGoogle

TOKEN = "s3cret-token"
AUTH = AuthSettings(
    google_client_id="client-id",
    google_client_secret="client-secret",
    session_secret="session-secret",
    base_url="http://testserver",
    api_token=TOKEN,
)


def _client(tmp_path: Path, auth: AuthSettings = AUTH, google: FakeGoogle | None = None):
    db_path = tmp_path / "t.db"
    seed(db_path)
    app = create_app(db_path, auth=auth, google=google or FakeGoogle())
    return TestClient(app, follow_redirects=False)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sign_in(client: TestClient, tmp_path: Path, google: FakeGoogle) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        auth_store.allow_email(conn, "owner@example.com", datetime(2026, 1, 1, tzinfo=UTC))
    finally:
        conn.close()
    google.signs_in("owner@example.com")
    client.get("/auth/google")
    client.get("/auth/callback")


def test_right_token_without_a_session_reaches_the_api(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/categories", headers=_bearer(TOKEN))

    assert response.status_code == 200


def test_wrong_token_answers_401_json(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/categories", headers=_bearer("wrong"))

    assert response.status_code == 401
    assert "error" in response.json()


def test_non_ascii_token_answers_401_instead_of_crashing(tmp_path):
    headers = {b"authorization": "Bearer tökén".encode()}
    with _client(tmp_path) as client:
        response = client.get("/api/categories", headers=headers)

    assert response.status_code == 401


def test_wrong_token_is_refused_even_with_a_signed_in_session(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google=google) as client:
        _sign_in(client, tmp_path, google)
        response = client.get("/api/categories", headers=_bearer("wrong"))

    assert response.status_code == 401


def test_no_header_and_no_cookie_answers_401(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/categories")

    assert response.status_code == 401


def test_a_basic_header_is_not_a_bearer_token(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/api/categories", headers={"Authorization": f"Basic {TOKEN}"})

    assert response.status_code == 401


def test_the_token_never_opens_a_page(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/", headers=_bearer(TOKEN))

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


def test_a_signed_in_session_still_works_when_a_token_is_configured(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google=google) as client:
        _sign_in(client, tmp_path, google)
        response = client.get("/api/categories")

    assert response.status_code == 200


def test_a_bearer_header_without_a_configured_token_gets_nothing(tmp_path):
    with _client(tmp_path, auth=replace(AUTH, api_token=None)) as client:
        response = client.get("/api/categories", headers=_bearer(TOKEN))

    assert response.status_code == 401
