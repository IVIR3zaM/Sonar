"""Code-mode Google sign-in: the round trip ends on a one-time code page, not a session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sonar.web.app import create_app
from tests.html import soup, text
from tests.seed import seed
from tests.web.fake_google import FakeGoogle
from tests.web.test_auth_pages import AUTH, _allow, _client, _revoke, _session


def _code_mode_sign_in(client, google: FakeGoogle, email: str, verified: bool | None = True):
    google.signs_in(email, email_verified=verified)
    client.get("/auth/google?mode=code")
    return client.get("/auth/callback")


def test_code_mode_callback_shows_a_code_and_no_session(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        callback = _code_mode_sign_in(client, google, "owner@example.com")
        home = client.get("/")

        assert _session(client) == {}

    assert callback.status_code == 200
    assert callback.headers["cache-control"] == "no-store"
    assert "location" not in callback.headers
    code = soup(callback).select_one("#sign-in-code")
    assert code is not None
    assert text(code).isdigit() and len(text(code)) == 6
    assert home.status_code == 302
    assert home.headers["location"] == "/auth/login"


def test_code_page_is_bare_and_has_no_inline_style_or_script(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        page = soup(_code_mode_sign_in(client, google, "owner@example.com"))

    assert page.select_one("nav") is None
    assert page.select_one("style") is None
    assert page.select("#sign-in-code-card style, #sign-in-code-card script") == []
    assert "once" in text(page)


def test_sign_in_without_mode_still_redirects_home(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        google.signs_in("owner@example.com")
        client.get("/auth/google")
        callback = client.get("/auth/callback")

    assert callback.status_code == 302
    assert callback.headers["location"] == "/"


def test_normal_sign_in_after_an_earlier_code_mode_start_is_normal(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        client.get("/auth/google?mode=code")
        google.signs_in("owner@example.com")
        client.get("/auth/google")
        callback = client.get("/auth/callback")

    assert callback.status_code == 302
    assert callback.headers["location"] == "/"


def test_any_other_mode_value_is_a_normal_sign_in(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        google.signs_in("owner@example.com")
        client.get("/auth/google?mode=other")
        callback = client.get("/auth/callback")

    assert callback.status_code == 302
    assert callback.headers["location"] == "/"


def test_code_mode_with_an_unlisted_email_is_not_allowed(tmp_path):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        callback = _code_mode_sign_in(client, google, "stranger@example.com")

    assert callback.status_code == 403
    page = soup(callback)
    assert page.select_one("#not-allowed") is not None
    assert page.select_one("#sign-in-code") is None


@pytest.mark.parametrize("verified", [False, None])
def test_code_mode_with_an_unverified_email_is_not_allowed(tmp_path, verified):
    google = FakeGoogle()
    with _client(tmp_path, google) as client:
        _allow(tmp_path, "owner@example.com")
        callback = _code_mode_sign_in(client, google, "owner@example.com", verified=verified)

    assert callback.status_code == 403
    page = soup(callback)
    assert page.select_one("#not-allowed") is not None
    assert page.select_one("#sign-in-code") is None


# --- exchanging a code for a session in the browser that posts it ---

ERROR_TEXT = "That code did not work. Sign in with Google again to get a new one."
ORIGIN = {"Origin": "http://testserver"}


class Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.at


class Pair:
    """One server with two browsers: Safari signs in with Google, the home-screen app posts."""

    def __init__(self, tmp_path, google: FakeGoogle, clock: Clock) -> None:
        seed(tmp_path / "t.db")
        server = create_app(tmp_path / "t.db", auth=AUTH, google=google, now=clock)
        self.google = google
        self.safari = TestClient(server, follow_redirects=False)
        self.app = TestClient(server, follow_redirects=False)

    def code_for(self, email: str) -> str:
        callback = _code_mode_sign_in(self.safari, self.google, email)
        return text(soup(callback).select_one("#sign-in-code"))


@pytest.fixture
def pair(tmp_path):
    both = Pair(tmp_path, FakeGoogle(), Clock())
    _allow(tmp_path, "owner@example.com")
    with both.safari, both.app:
        yield both


def _post_code(client: TestClient, code: str, headers: dict | None = ORIGIN):
    return client.post("/auth/code", data={"code": code}, headers=headers)


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def _error_text(response) -> str:
    return text(soup(response).select_one("#field-code-error"))


def test_exchange_code_signs_in_the_posting_client(pair):
    code = pair.code_for("owner@example.com")
    response = _post_code(pair.app, code)
    home = pair.app.get("/")
    api = pair.app.get("/api/categories")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert home.status_code == 200
    assert api.status_code == 200
    assert "Max-Age=1209600" in response.headers["set-cookie"]
    assert _session(pair.app) == {"email": "owner@example.com"}
    assert _session(pair.safari) == {}


def _assert_rejected(response, app: TestClient, code: str) -> None:
    assert response.status_code == 400
    assert _error_text(response) == ERROR_TEXT
    assert soup(response).select_one("#field-code")["value"] == code
    assert _session(app) == {}
    assert app.get("/").status_code == 302


def test_wrong_code_is_rejected(pair):
    code = pair.code_for("owner@example.com")
    bad = _wrong(code)
    _assert_rejected(_post_code(pair.app, bad), pair.app, bad)


def test_malformed_code_is_rejected_with_the_same_error(pair):
    pair.code_for("owner@example.com")
    _assert_rejected(_post_code(pair.app, "12ab"), pair.app, "12ab")


def test_expired_code_is_rejected(tmp_path):
    clock = Clock()
    pair = Pair(tmp_path, FakeGoogle(), clock)
    _allow(tmp_path, "owner@example.com")
    with pair.safari, pair.app:
        code = pair.code_for("owner@example.com")
        clock.at += timedelta(minutes=5)
        _assert_rejected(_post_code(pair.app, code), pair.app, code)


def test_reused_code_is_rejected(pair):
    code = pair.code_for("owner@example.com")
    assert _post_code(pair.app, code).status_code == 303
    pair.app.cookies.clear()
    _assert_rejected(_post_code(pair.app, code), pair.app, code)


def test_revoked_email_code_is_rejected(tmp_path, pair):
    code = pair.code_for("owner@example.com")
    _revoke(tmp_path, "owner@example.com")
    _assert_rejected(_post_code(pair.app, code), pair.app, code)


def test_all_rejections_share_one_error_text(tmp_path):
    clock = Clock()
    pair = Pair(tmp_path, FakeGoogle(), clock)
    _allow(tmp_path, "owner@example.com")
    with pair.safari, pair.app:
        code = pair.code_for("owner@example.com")
        texts = {
            _error_text(_post_code(pair.app, _wrong(code))),
            _error_text(_post_code(pair.app, "abc")),
        }
        clock.at += timedelta(minutes=5)
        texts.add(_error_text(_post_code(pair.app, code)))

    assert texts == {ERROR_TEXT}


def test_rate_limit_sixth_post_in_the_window_is_429_even_with_a_valid_code(pair):
    code = pair.code_for("owner@example.com")
    for _ in range(5):
        assert _post_code(pair.app, _wrong(code)).status_code == 400
    # Five failures void the pending code, so issue a fresh, valid one.
    fresh = pair.code_for("owner@example.com")
    limited = _post_code(pair.app, fresh)

    assert limited.status_code == 429
    assert pair.app.get("/").status_code == 302


def test_rate_limit_five_wrong_codes_void_a_pending_valid_code(pair):
    code = pair.code_for("owner@example.com")
    for _ in range(5):
        _post_code(pair.app, _wrong(code))
    elsewhere = TestClient(pair.app.app, follow_redirects=False, client=("203.0.113.9", 50000))
    with elsewhere:
        response = _post_code(elsewhere, code)

    assert response.status_code == 400
    assert _session(elsewhere) == {}


def test_foreign_origin_is_403_and_costs_no_attempt(pair):
    code = pair.code_for("owner@example.com")
    foreign = _post_code(pair.app, code, {"Origin": "http://evil.example"})
    neither = _post_code(pair.app, code, {})

    assert foreign.status_code == 403
    assert neither.status_code == 403
    assert _error_text(foreign) == ERROR_TEXT
    assert _post_code(pair.app, code).status_code == 303


def test_referer_under_the_base_url_stands_in_for_origin(pair):
    code = pair.code_for("owner@example.com")
    lookalike = _post_code(pair.app, code, {"Referer": "http://testserver.evil.example/auth/login"})
    legit = _post_code(pair.app, code, {"Referer": "http://testserver/auth/login"})

    assert lookalike.status_code == 403
    assert legit.status_code == 303


def test_get_auth_code_is_405(pair):
    assert pair.app.get("/auth/code").status_code == 405
