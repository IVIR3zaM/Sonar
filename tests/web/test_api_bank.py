"""`GET /api/bank` and `POST /api/bank/sync` (SPEC §13 Bank sync), with a fake bank client."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.banking.client import BankApiError
from sonar.banking.consent import NewConnection
from sonar.banking.settings import BankSettings
from sonar.banking.store import save_connection
from sonar.db import connect
from sonar.web.app import create_app
from tests.seed import seed
from tests.web.fake_bank import FakeBank, booked_debit, listed_balance

BANK = BankSettings(
    app_id="app-id",
    key_path=Path("unused.pem"),
    redirect_url="http://testserver/bank/callback",
)
TODAY = date(2026, 10, 14)
NOON = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _client(tmp_path: Path, bank: FakeBank | None) -> TestClient:
    db_path = tmp_path / "t.db"
    seed(db_path)
    app = create_app(
        db_path,
        today=lambda: TODAY,
        now=lambda: NOON,
        bank=BANK if bank is not None else None,
        bank_client=bank,
    )
    return TestClient(app, follow_redirects=False)


def _connect_bank(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        save_connection(
            conn,
            NewConnection(
                session_id="session-1",
                account_uid="account-1",
                iban_last4="1234",
                consent_valid_until=NOON + timedelta(days=60),
                connected_at=NOON - timedelta(days=1),
            ),
        )
    finally:
        conn.close()


def test_get_bank_not_connected(tmp_path):
    with _client(tmp_path, FakeBank()) as client:
        response = client.get("/api/bank")

    assert response.status_code == 200
    assert response.json() == {
        "status": "Not connected",
        "iban_last4": None,
        "consent_valid_until": None,
        "last_sync": None,
    }


def test_get_bank_connected_has_no_session_id_or_account_uid(tmp_path):
    with _client(tmp_path, FakeBank()) as client:
        _connect_bank(tmp_path)
        response = client.get("/api/bank")

    assert response.json() == {
        "status": "Connected",
        "iban_last4": "1234",
        "consent_valid_until": "2026-12-13T12:00:00+00:00",
        "last_sync": None,
    }
    assert "session-1" not in response.text
    assert "account-1" not in response.text


def test_post_sync_runs_the_sync_and_returns_it(tmp_path):
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1"), booked_debit("ref-2", amount="1.00")]
    bank.balance_list = [listed_balance("1234.56")]
    with _client(tmp_path, bank) as client:
        _connect_bank(tmp_path)
        response = client.post("/api/bank/sync")
        status = client.get("/api/bank").json()

    assert response.status_code == 200
    body = response.json()
    assert (body["added"], body["duplicates"]) == (2, 0)
    assert body["balance"] == {"amount_cents": 123456, "as_of": "2026-10-14"}
    assert body["bank"] == status
    assert status["last_sync"] == {
        "at": "2026-10-14T12:00:00+00:00",
        "status": "ok",
        "added": 2,
        "error": None,
    }
    assert "session-1" not in response.text
    assert "account-1" not in response.text


def test_post_sync_without_a_connection_is_409(tmp_path):
    bank = FakeBank()
    with _client(tmp_path, bank) as client:
        response = client.post("/api/bank/sync")

    assert response.status_code == 409
    assert response.json() == {"error": "Bank is not connected."}
    assert bank.windows == []


def test_post_sync_when_enable_banking_fails_is_502(tmp_path):
    bank = FakeBank()
    bank.error = BankApiError(503, "Enable Banking answered 503")
    with _client(tmp_path, bank) as client:
        _connect_bank(tmp_path)
        response = client.post("/api/bank/sync")
        status = client.get("/api/bank").json()

    assert response.status_code == 502
    assert response.json() == {"error": "Enable Banking answered 503"}
    assert status["last_sync"]["status"] == "error"
    assert status["last_sync"]["error"] == "Enable Banking answered 503"


def test_bank_off_has_no_bank_api(tmp_path):
    with _client(tmp_path, None) as client:
        assert client.get("/api/bank").status_code == 404
        assert client.post("/api/bank/sync").status_code == 404
