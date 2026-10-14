"""Tests for `sonar bank-sync` (SPEC §13 Bank sync), with a fake bank client."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from sonar.__main__ import bank_sync, main
from sonar.banking.client import BankApiError
from sonar.banking.consent import NewConnection
from sonar.banking.settings import BANK_ENV_VARS, BankSettings
from sonar.banking.store import load_connection, save_connection
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from tests.web.fake_bank import FakeBank, booked_debit, listed_balance

TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
BANK = BankSettings(app_id="app-id", key_path=Path("unused.pem"), redirect_url="http://x/cb")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.delenv("SONAR_DB_PATH", raising=False)
    for name in BANK_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "t.db"


def _connect_bank(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        save_connection(
            conn,
            NewConnection("session-1", "account-1", "1234", NOW + timedelta(days=90), NOW),
        )
    finally:
        conn.close()


def _bank(bank_client: FakeBank | None):
    return lambda: (BANK, bank_client) if bank_client else (None, None)


def _run(monkeypatch, bank_client: FakeBank | None, db_path: Path) -> None:
    monkeypatch.setattr("sonar.__main__._bank", _bank(bank_client))
    monkeypatch.setattr("sys.argv", ["sonar", "bank-sync", "--db", str(db_path)])
    main()


def test_without_bank_settings_it_says_not_configured_and_exits_0(db, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["sonar", "bank-sync", "--db", str(db)])

    main()

    assert capsys.readouterr().out.strip() == "Bank sync is not configured."


def test_without_a_connection_it_says_not_connected_and_exits_0(db, monkeypatch, capsys):
    _run(monkeypatch, FakeBank(), db)

    assert capsys.readouterr().out.strip() == "Bank is not connected."


def test_a_sync_prints_added_duplicates_and_the_balance(db, capsys):
    _connect_bank(db)
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1"), booked_debit("ref-2", amount="3.00")]
    bank.balance_list = [listed_balance("1234.56")]
    bank_sync(db, bank, TODAY, NOW)
    capsys.readouterr()
    bank.booked.append(booked_debit("ref-3", amount="4.00"))

    bank_sync(db, bank, TODAY, NOW + timedelta(hours=1))

    assert capsys.readouterr().out.strip() == (
        "Bank sync: 1 added, 2 duplicates, balance 1234.56 on 2026-10-14."
    )


def test_a_negative_balance_keeps_its_sign(db, capsys):
    _connect_bank(db)
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]
    bank.balance_list = [listed_balance("-0.05")]

    bank_sync(db, bank, TODAY, NOW)

    assert capsys.readouterr().out.strip().endswith("balance -0.05 on 2026-10-14.")


def test_the_command_runs_the_sync(db, monkeypatch, capsys):
    _connect_bank(db)
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]
    bank.balance_list = [listed_balance("10.00")]

    _run(monkeypatch, bank, db)

    assert capsys.readouterr().out.startswith("Bank sync: 1 added, 0 duplicates, balance 10.00")


def test_a_failed_sync_prints_the_message_and_exits_1(db, monkeypatch, capsys):
    _connect_bank(db)
    bank = FakeBank()
    bank.error = BankApiError(503, "Enable Banking answered 503")

    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, bank, db)

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.strip() == "Bank sync failed: Enable Banking answered 503"
    conn = connect(db)
    try:
        assert load_connection(conn).last_sync_status == "error"
    finally:
        conn.close()


def test_output_never_holds_the_session_id_or_account_uid(db, monkeypatch, capsys):
    _connect_bank(db)
    bank = FakeBank()
    bank.booked = [booked_debit("ref-1")]

    _run(monkeypatch, bank, db)

    out = capsys.readouterr().out
    assert "session-1" not in out
    assert "account-1" not in out
