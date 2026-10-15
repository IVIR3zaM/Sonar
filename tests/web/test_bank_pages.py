"""Bank connect flow and the Settings card (SPEC §13 Bank sync), with a fake bank client."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.auth import store as auth_store
from sonar.auth.settings import AuthSettings
from sonar.banking.client import BankApiError
from sonar.banking.settings import BankSettings
from sonar.banking.store import load_connection
from sonar.db import connect
from sonar.web.app import create_app
from tests.html import soup, text
from tests.seed import seed
from tests.web.fake_bank import BANK_AUTH_URL, FakeBank, booked_debit
from tests.web.fake_google import FakeGoogle

BANK = BankSettings(
    app_id="app-id",
    key_path=Path("unused.pem"),
    redirect_url="http://testserver/bank/callback",
)
START = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
FAILURE = "The bank connection did not complete. Start again with Connect bank."


class Clock:
    def __init__(self) -> None:
        self.moment = START

    def __call__(self) -> datetime:
        return self.moment


def _client(tmp_path: Path, bank: FakeBank | None, clock: Clock | None = None, **kwargs):
    db_path = tmp_path / "t.db"
    seed(db_path)
    app = create_app(
        db_path,
        today=lambda: date(2026, 10, 14),
        now=clock or Clock(),
        bank=BANK if bank is not None else None,
        bank_client=bank,
        **kwargs,
    )
    return TestClient(app, follow_redirects=False)


def _stored(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    try:
        return load_connection(conn)
    finally:
        conn.close()


def _connect(client: TestClient, bank: FakeBank) -> str:
    response = client.post("/bank/connect")
    assert response.status_code == 303
    return bank.states[-1]


def _assert_failed(response) -> None:
    assert response.status_code == 400
    assert text(soup(response).select_one("#form-error")) == FAILURE


def test_connect_redirects_to_the_bank(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        response = client.post("/bank/connect")

    assert response.status_code == 303
    assert response.headers["location"] == BANK_AUTH_URL
    assert bank.redirect_urls == [BANK.redirect_url]
    # The longest consent of Deutsche Bank (not the other bank), less the request margin.
    assert bank.valid_untils == [START + timedelta(seconds=15552000) - timedelta(minutes=10)]


def test_connect_failure_shows_the_error(tmp_path):
    bank = FakeBank()
    bank.error = BankApiError(500, "Enable Banking answered 500")
    with _client(tmp_path, bank) as client:
        response = client.post("/bank/connect")

    _assert_failed(response)


def test_valid_callback_connects_and_shows_the_last_four_digits(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        callback = client.get("/bank/callback", params={"code": "the-code", "state": state})
        page = soup(client.get("/settings"))

    assert callback.status_code == 303
    assert callback.headers["location"] == "/settings"
    assert bank.codes == ["the-code"]
    card = page.select_one("#bank-card")
    assert card["data-bank-status"] == "connected"
    assert "Deutsche Bank ···1234" in text(card)
    assert text(page.select_one("#bank-connect")) == "Reconnect bank"
    assert _stored(tmp_path).iban_last4 == "1234"


def test_not_connected_card_offers_connect(tmp_path):
    with _client(tmp_path, FakeBank()) as client:
        page = soup(client.get("/settings"))

    assert page.select_one("#bank-card")["data-bank-status"] == "not-connected"
    assert text(page.select_one("#bank-connect")) == "Connect bank"


def test_second_callback_replaces_the_connection(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        client.get("/bank/callback", params={"code": "c1", "state": state})
        bank.iban = "DE00000000000000005678"
        bank.session_id = "session-2"
        state = _connect(client, bank)
        client.get("/bank/callback", params={"code": "c2", "state": state})

    stored = _stored(tmp_path)
    assert stored.iban_last4 == "5678"
    assert stored.session_id == "session-2"


def test_wrong_state_is_refused_and_burns_the_pending_one(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        wrong = client.get("/bank/callback", params={"code": "c", "state": "wrong"})
        genuine = client.get("/bank/callback", params={"code": "c", "state": state})

    _assert_failed(wrong)
    _assert_failed(genuine)
    assert _stored(tmp_path) is None
    assert bank.codes == []


def test_reused_state_is_refused(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        first = client.get("/bank/callback", params={"code": "c", "state": state})
        second = client.get("/bank/callback", params={"code": "c", "state": state})

    assert first.status_code == 303
    _assert_failed(second)
    assert bank.codes == ["c"]


def test_state_without_a_pending_one_is_refused(tmp_path):
    with _client(tmp_path, FakeBank()) as client:
        response = client.get("/bank/callback", params={"code": "c", "state": "anything"})

    _assert_failed(response)
    assert _stored(tmp_path) is None


def test_expired_state_is_refused(tmp_path):
    bank = FakeBank()
    clock = Clock()
    with _client(tmp_path, bank, clock) as client:
        state = _connect(client, bank)
        clock.moment = START + timedelta(minutes=31)
        response = client.get("/bank/callback", params={"code": "c", "state": state})

    _assert_failed(response)
    assert _stored(tmp_path) is None
    assert bank.codes == []


@pytest.mark.parametrize("missing", ["code", "state"])
def test_callback_missing_a_parameter_is_refused(tmp_path, missing):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        params = {"code": "c", "state": state}
        del params[missing]
        response = client.get("/bank/callback", params=params)

    _assert_failed(response)
    assert _stored(tmp_path) is None


def test_callback_with_an_error_param_is_refused(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        response = client.get(
            "/bank/callback", params={"code": "c", "state": state, "error": "access_denied"}
        )

    _assert_failed(response)
    assert _stored(tmp_path) is None
    assert bank.codes == []


def test_bank_api_error_on_callback_is_refused(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        bank.error = BankApiError(400, "Enable Banking answered 400")
        response = client.get("/bank/callback", params={"code": "c", "state": state})

    _assert_failed(response)
    assert _stored(tmp_path) is None


def test_unusable_session_is_refused(tmp_path):
    bank = FakeBank()
    bank.accounts = []
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        response = client.get("/bank/callback", params={"code": "c", "state": state})

    _assert_failed(response)
    assert _stored(tmp_path) is None


def test_failure_page_leaks_no_secret(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        response = client.get(
            "/bank/callback", params={"code": "secret-code", "state": "wrong-" + state}
        )

    assert "secret-code" not in response.text
    assert state not in response.text


def test_bank_off_has_no_routes_and_no_card(tmp_path):
    with _client(tmp_path, None) as client:
        connect_response = client.post("/bank/connect")
        callback = client.get("/bank/callback", params={"code": "c", "state": "s"})
        page = soup(client.get("/settings"))

    assert connect_response.status_code == 404
    assert callback.status_code == 404
    assert page.select_one("#bank-card") is None


AUTH = AuthSettings(
    google_client_id="client-id",
    google_client_secret="client-secret",
    session_secret="session-secret",
    base_url="http://testserver",
)


def _sign_in_client(tmp_path: Path, bank: FakeBank, google: FakeGoogle):
    return _client(tmp_path, bank, auth=AUTH, google=google)


def test_sign_in_gates_the_callback(tmp_path):
    bank = FakeBank()
    with _sign_in_client(tmp_path, bank, FakeGoogle()) as client:
        response = client.get("/bank/callback", params={"code": "c", "state": "s"})

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"
    assert bank.codes == []
    assert _stored(tmp_path) is None


def test_sign_in_signed_in_get_connect_is_405(tmp_path):
    bank = FakeBank()
    google = FakeGoogle()
    with _sign_in_client(tmp_path, bank, google) as client:
        conn = connect(tmp_path / "t.db")
        try:
            auth_store.allow_email(conn, "owner@example.com", START)
        finally:
            conn.close()
        google.signs_in("owner@example.com")
        client.get("/auth/google")
        client.get("/auth/callback")
        response = client.get("/bank/connect")

    assert response.status_code == 405


@contextmanager
def _connected_client(tmp_path: Path, bank: FakeBank) -> Iterator[TestClient]:
    with _client(tmp_path, bank) as client:
        state = _connect(client, bank)
        client.get("/bank/callback", params={"code": "the-code", "state": state})
        yield client


def _synced_rows(tmp_path: Path) -> list[str]:
    conn = connect(tmp_path / "t.db")
    try:
        return [r[0] for r in conn.execute("SELECT entry_reference FROM transactions")]
    finally:
        conn.close()


def test_connected_card_offers_sync_now(tmp_path):
    bank = FakeBank()
    with _connected_client(tmp_path, bank) as client:
        page = soup(client.get("/settings"))

    form = page.select_one("#bank-card #bank-sync")
    assert form["method"] == "post"
    assert form["action"] == "/bank/sync"
    assert text(form.select_one("button[type=submit] [data-label=idle]")) == "Sync now"


def test_sync_now_form_has_an_htmx_loading_state(tmp_path):
    with _connected_client(tmp_path, FakeBank()) as client:
        page = soup(client.get("/settings"))

    form = page.select_one("#bank-sync")
    button = form.select_one("button[type=submit]")
    assert form["method"] == "post"
    assert form["action"] == "/bank/sync"
    assert form["hx-post"] == "/bank/sync"
    assert form.has_attr("hx-disabled-elt")
    assert button.select_one("#bank-sync-spinner") is not None
    assert text(button.select_one("[data-label=idle]")) == "Sync now"
    assert text(button.select_one("[data-label=busy]")) == "Syncing…"


def test_connected_card_subtitle_says_synced_three_times_a_day(tmp_path):
    with _connected_client(tmp_path, FakeBank()) as client:
        page = soup(client.get("/settings"))

    assert "synced three times a day" in text(page.select_one("#bank-card"))


def test_htmx_sync_now_answers_204_with_hx_redirect(tmp_path):
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]
    with _connected_client(tmp_path, bank) as client:
        response = client.post("/bank/sync", headers={"HX-Request": "true"})

    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/settings"
    assert _synced_rows(tmp_path) == ["ref-1"]


@pytest.mark.parametrize(
    ("moment", "shown"),
    [
        (datetime(2026, 10, 14, 12, 0, tzinfo=UTC), "14 Oct 2026 14:00 CEST"),
        (datetime(2026, 12, 1, 12, 0, tzinfo=UTC), "1 Dec 2026 13:00 CET"),
    ],
)
def test_last_sync_is_shown_in_berlin_time(tmp_path, moment, shown):
    bank = FakeBank()
    clock = Clock()
    with _client(tmp_path, bank, clock) as client:
        state = _connect(client, bank)
        client.get("/bank/callback", params={"code": "the-code", "state": state})
        clock.moment = moment
        client.post("/bank/sync")
        page = soup(client.get("/settings"))
        api = client.get("/api/bank").json()

    time = page.select_one("#bank-last-sync time")
    assert text(time) == shown
    assert "UTC" not in text(time)
    assert time["datetime"] == moment.isoformat()
    assert api["last_sync"]["at"] == moment.isoformat()


def test_not_connected_card_has_no_sync_now(tmp_path):
    with _client(tmp_path, FakeBank()) as client:
        page = soup(client.get("/settings"))

    assert page.select_one("#bank-sync") is None


def test_sync_now_imports_and_redirects_to_settings(tmp_path):
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]
    with _connected_client(tmp_path, bank) as client:
        response = client.post("/bank/sync")
        page = soup(client.get("/settings"))

    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    assert _synced_rows(tmp_path) == ["ref-1"]
    assert bank.windows[0][1:] == (date(2026, 7, 16), date(2026, 10, 14))
    last_sync = page.select_one("#bank-last-sync")
    assert text(last_sync.select_one("[data-field=status]")) == "ok"
    assert text(last_sync.select_one("[data-field=added]")) == "1"


def test_failed_sync_now_redirects_and_shows_the_error(tmp_path):
    bank = FakeBank()
    with _connected_client(tmp_path, bank) as client:
        bank.error = BankApiError(503, "Enable Banking answered 503")
        response = client.post("/bank/sync")
        page = soup(client.get("/settings"))

    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    last_sync = page.select_one("#bank-last-sync")
    assert text(last_sync.select_one("[data-field=error]")) == "Enable Banking answered 503"


def test_sync_now_without_a_connection_redirects_to_settings(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        response = client.post("/bank/sync")

    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    assert bank.windows == []


def test_bank_off_has_no_sync_route(tmp_path):
    with _client(tmp_path, None) as client:
        assert client.post("/bank/sync").status_code == 404
