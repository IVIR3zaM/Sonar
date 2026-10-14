"""The bank banner on every page (SPEC §13 Bank sync), with a fake bank client."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.banking.consent import NewConnection
from sonar.banking.settings import BankSettings
from sonar.banking.store import save_connection
from sonar.db import connect
from sonar.web.app import create_app
from tests.html import soup, text
from tests.seed import seed
from tests.web.fake_bank import FakeBank

BANK = BankSettings(
    app_id="app-id",
    key_path=Path("unused.pem"),
    redirect_url="http://testserver/bank/callback",
)
TODAY = date(2026, 10, 14)
NOON = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _client(tmp_path: Path, bank_on: bool = True) -> TestClient:
    db_path = tmp_path / "t.db"
    seed(db_path)
    app = create_app(
        db_path,
        today=lambda: TODAY,
        now=lambda: NOON,
        bank=BANK if bank_on else None,
        bank_client=FakeBank() if bank_on else None,
    )
    return TestClient(app, follow_redirects=False)


def _connection_ending_in(tmp_path: Path, days: int) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        save_connection(
            conn,
            NewConnection(
                session_id="session-1",
                account_uid="account-1",
                iban_last4="1234",
                consent_valid_until=NOON + timedelta(days=days),
                connected_at=NOON - timedelta(days=30),
            ),
        )
    finally:
        conn.close()


def _failed_sync(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        with conn:
            conn.execute(
                "UPDATE bank_connection SET last_sync_at = ?, last_sync_status = 'error', "
                "last_sync_error = 'Enable Banking answered 500'",
                ((NOON - timedelta(days=1)).isoformat(),),
            )
    finally:
        conn.close()


def _banner(client: TestClient):
    response = client.get("/bank/banner")
    assert response.status_code == 200
    return soup(response).select_one("#bank-banner")


def _assert_reconnect_form(banner) -> None:
    form = banner.select_one("form[action='/bank/connect']")
    assert form["method"] == "post"
    assert form.select_one("button[type=submit]") is not None


def test_expiring_connection_shows_the_expiring_banner(tmp_path):
    with _client(tmp_path) as client:
        _connection_ending_in(tmp_path, 10)
        banner = _banner(client)

    assert banner["data-banner"] == "expiring"
    assert "Bank access ends on 24 Oct 2026." in text(banner)
    _assert_reconnect_form(banner)


def test_expired_connection_shows_the_expired_banner(tmp_path):
    with _client(tmp_path) as client:
        _connection_ending_in(tmp_path, -2)
        banner = _banner(client)

    assert banner["data-banner"] == "expired"
    assert "Bank access ended on 12 Oct 2026." in text(banner)
    _assert_reconnect_form(banner)


def test_failed_sync_shows_the_failed_banner(tmp_path):
    with _client(tmp_path) as client:
        _connection_ending_in(tmp_path, 60)
        _failed_sync(tmp_path)
        banner = _banner(client)

    assert banner["data-banner"] == "failed"
    assert "The bank sync on 13 Oct 2026 failed: Enable Banking answered 500." in text(banner)
    _assert_reconnect_form(banner)


def test_banner_holds_no_session_id_or_account_uid(tmp_path):
    with _client(tmp_path) as client:
        _connection_ending_in(tmp_path, 10)
        response = client.get("/bank/banner")

    assert "session-1" not in response.text
    assert "account-1" not in response.text
    assert "style=" not in response.text


def test_healthy_connection_has_an_empty_fragment(tmp_path):
    with _client(tmp_path) as client:
        _connection_ending_in(tmp_path, 60)
        response = client.get("/bank/banner")

    assert response.status_code == 200
    assert response.text.strip() == ""


def test_no_connection_has_an_empty_fragment(tmp_path):
    with _client(tmp_path) as client:
        response = client.get("/bank/banner")

    assert response.status_code == 200
    assert response.text.strip() == ""


@pytest.mark.parametrize("path", ["/", "/settings"])
def test_slot_loads_the_banner_when_bank_is_on(tmp_path, path):
    with _client(tmp_path) as client:
        slot = soup(client.get(path)).select_one("#bank-banner-slot")

    assert slot["hx-get"] == "/bank/banner"
    assert slot["hx-trigger"] == "load"


@pytest.mark.parametrize("path", ["/", "/settings"])
def test_bank_off_has_no_slot_and_no_banner_route(tmp_path, path):
    with _client(tmp_path, bank_on=False) as client:
        page = soup(client.get(path))
        banner = client.get("/bank/banner")

    assert page.select_one("#bank-banner-slot") is None
    assert banner.status_code == 404


def test_failed_banner_offers_sync_now(tmp_path):
    with _client(tmp_path) as client:
        _connection_ending_in(tmp_path, 60)
        _failed_sync(tmp_path)
        banner = _banner(client)

    form = banner.select_one("form[action='/bank/sync']")
    assert form["method"] == "post"
    assert text(form.select_one("button[type=submit]")) == "Sync now"


@pytest.mark.parametrize("days", [10, -2])
def test_consent_banners_offer_no_sync_now(tmp_path, days):
    with _client(tmp_path) as client:
        _connection_ending_in(tmp_path, days)
        banner = _banner(client)

    assert banner.select_one("form[action='/bank/sync']") is None
