"""Tests for banking/service.py: the daily sync through the import pipeline (SPEC §13 Bank sync)."""

import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from sonar.banking import mapping
from sonar.banking.client import BankApiError
from sonar.banking.consent import NewConnection
from sonar.banking.service import NotConnectedError, sync
from sonar.banking.store import load_connection, save_connection
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.importing.importers import deutsche_bank_giro
from sonar.importing.store import import_rows
from sonar.transactions import ParsedTransaction
from tests.web.fake_bank import OWN_IBAN, FakeBank, booked_debit, listed_balance

TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
CSV_ACCOUNT = "DE00000000000000009999"


def _connected() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    save_connection(
        conn,
        NewConnection(
            session_id="session-1",
            account_uid="account-1",
            iban_last4="1234",
            consent_valid_until=NOW + timedelta(days=150),
            connected_at=NOW - timedelta(days=1),
        ),
    )
    return conn


def _rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT source, account, amount_cents, entry_reference FROM transactions ORDER BY id"
    ).fetchall()


def _balances(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT account, as_of, amount_cents, source FROM balances ORDER BY id"
    ).fetchall()


def test_not_connected_raises_and_calls_nothing():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    bank = FakeBank()

    with pytest.raises(NotConnectedError):
        sync(conn, bank, TODAY, NOW)

    assert bank.windows == []


def test_the_first_sync_fetches_the_last_90_days():
    conn = _connected()
    bank = FakeBank()

    sync(conn, bank, TODAY, NOW)

    assert bank.windows == [("account-1", TODAY - timedelta(days=90), TODAY)]


def test_a_later_sync_fetches_from_the_last_successful_sync_less_7_days():
    conn = _connected()
    bank = FakeBank()
    sync(conn, bank, date(2026, 10, 10), datetime(2026, 10, 10, 6, 0, tzinfo=UTC))

    sync(conn, bank, TODAY, NOW)

    assert bank.windows[-1] == ("account-1", date(2026, 10, 3), TODAY)


def test_a_sync_after_a_failed_one_fetches_the_full_first_window():
    conn = _connected()
    bank = FakeBank()
    bank.error = BankApiError(500, "Enable Banking answered 500")
    with pytest.raises(BankApiError):
        sync(conn, bank, date(2026, 10, 13), NOW - timedelta(days=1))
    bank.error = None

    sync(conn, bank, TODAY, NOW)

    assert bank.windows[-1] == ("account-1", TODAY - timedelta(days=90), TODAY)


def test_synced_rows_are_stored_with_the_api_source_and_reference():
    conn = _connected()
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1"), booked_debit("ref-2", amount="5.00")]

    result = sync(conn, bank, TODAY, NOW)

    assert (result.added, result.duplicates) == (2, 0)
    assert _rows(conn) == [
        (mapping.SOURCE, OWN_IBAN, -1234, "ref-1"),
        (mapping.SOURCE, OWN_IBAN, -500, "ref-2"),
    ]


def test_a_repeated_sync_adds_nothing():
    conn = _connected()
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1"), booked_debit("ref-2", amount="5.00")]
    sync(conn, bank, TODAY, NOW)

    result = sync(conn, bank, TODAY, NOW + timedelta(hours=1))

    assert (result.added, result.duplicates) == (0, 2)
    assert len(_rows(conn)) == 2


def test_an_api_row_matching_a_stored_csv_row_adds_nothing():
    conn = _connected()
    csv_row = ParsedTransaction(
        account=CSV_ACCOUNT,
        booking_date=date(2026, 10, 12),
        value_date=date(2026, 10, 12),
        amount_cents=-1234,
        currency="EUR",
        counterparty="Grocer Example",
        purpose="Card payment",
        raw_row="anonymized",
    )
    import_rows(conn, deutsche_bank_giro.NAME, [csv_row])
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]

    result = sync(conn, bank, TODAY, NOW)

    assert (result.added, result.duplicates) == (0, 1)
    assert _rows(conn) == [(deutsche_bank_giro.NAME, CSV_ACCOUNT, -1234, "ref-1")]


def test_the_balance_is_upserted_so_the_days_latest_sync_wins():
    conn = _connected()
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]
    bank.balance_list = [listed_balance("100.00")]
    sync(conn, bank, TODAY, NOW)
    bank.balance_list = [listed_balance("1234.56")]

    result = sync(conn, bank, TODAY, NOW + timedelta(hours=2))

    assert result.balance.amount_cents == 123456
    assert _balances(conn) == [(OWN_IBAN, "2026-10-14", 123456, "import")]


def test_a_successful_sync_records_time_status_and_rows_added():
    conn = _connected()
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]

    sync(conn, bank, TODAY, NOW)

    stored = load_connection(conn)
    assert (stored.last_sync_at, stored.last_sync_status, stored.last_sync_added) == (
        NOW,
        "ok",
        1,
    )
    assert stored.last_sync_error is None


def test_an_api_error_is_recorded_and_earlier_rows_are_kept():
    conn = _connected()
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]
    sync(conn, bank, TODAY, NOW)
    bank.error = BankApiError(503, "Enable Banking answered 503")
    later = NOW + timedelta(hours=3)

    with pytest.raises(BankApiError):
        sync(conn, bank, TODAY, later)

    stored = load_connection(conn)
    assert (stored.last_sync_at, stored.last_sync_status) == (later, "error")
    assert stored.last_sync_error == "Enable Banking answered 503"
    assert len(_rows(conn)) == 1


def test_an_unreadable_payload_is_recorded_as_an_error():
    conn = _connected()
    bank = FakeBank()
    unreadable = booked_debit("ref-1")
    del unreadable["transaction_amount"]
    bank.booked = [unreadable]

    with pytest.raises(BankApiError):
        sync(conn, bank, TODAY, NOW)

    stored = load_connection(conn)
    assert stored.last_sync_status == "error"
    assert _rows(conn) == []


def test_synced_rows_are_categorized_by_the_stored_rules():
    conn = _connected()
    with conn:
        category_id = conn.execute(
            "INSERT INTO categories (name, type) VALUES ('Test groceries', 'lights_on')"
        ).lastrowid
        conn.execute(
            "INSERT INTO category_rules (position, category_id, counterparty) "
            "VALUES (0, ?, 'Grocer Example')",
            (category_id,),
        )
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]

    sync(conn, bank, TODAY, NOW)

    assert conn.execute("SELECT category FROM transactions").fetchone() == ("Test groceries",)
