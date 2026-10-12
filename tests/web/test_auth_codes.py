"""Code-mode Google sign-in: the round trip ends on a one-time code page, not a session."""

from __future__ import annotations

import pytest

from tests.html import soup, text
from tests.web.fake_google import FakeGoogle
from tests.web.test_auth_pages import _allow, _client, _session


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
