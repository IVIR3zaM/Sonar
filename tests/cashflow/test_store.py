"""Tests for cashflow/store.py: salary day, overdraft limit, manual balance (SPEC §8, §4)."""

import sqlite3
from datetime import date

import pytest

from sonar.cashflow.balance import BalanceEntry
from sonar.cashflow.store import (
    DEFAULT_OVERDRAFT_LIMIT_CENTS,
    Settings,
    current_balance,
    load_settings,
    save_settings,
    set_manual_balance,
)
from sonar.db import MIGRATIONS_DIR, apply_migrations


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_load_settings_unconfigured_returns_default_limit():
    conn = _connect_migrated()
    assert load_settings(conn) == Settings(
        salary_day=None, overdraft_limit_cents=DEFAULT_OVERDRAFT_LIMIT_CENTS
    )


def test_save_then_load_settings():
    conn = _connect_migrated()
    save_settings(conn, 26, -75050)
    assert load_settings(conn) == Settings(salary_day=26, overdraft_limit_cents=-75050)


def test_saving_again_overwrites_and_leaves_one_row():
    conn = _connect_migrated()
    save_settings(conn, 26, -75050)
    save_settings(conn, 10, -20000)

    assert load_settings(conn) == Settings(salary_day=10, overdraft_limit_cents=-20000)
    row_count = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
    assert row_count == 1


@pytest.mark.parametrize(
    "salary_day,overdraft_limit_cents",
    [
        (0, -50000),  # salary_day below the valid range
        (32, -50000),  # salary_day above the valid range
        (26, 1),  # positive overdraft limit is not allowed
    ],
    ids=["day_0", "day_32", "positive_limit"],
)
def test_save_settings_invalid_raises_and_leaves_row_unchanged(
    salary_day: int, overdraft_limit_cents: int
):
    conn = _connect_migrated()
    save_settings(conn, 26, -50000)  # a prior valid save must survive the failed one

    with pytest.raises(ValueError):
        save_settings(conn, salary_day, overdraft_limit_cents)

    assert load_settings(conn) == Settings(salary_day=26, overdraft_limit_cents=-50000)


def test_manual_balance_dated_tomorrow_raises_and_inserts_nothing():
    conn = _connect_migrated()
    today = date(2026, 9, 23)
    tomorrow = date(2026, 9, 24)

    with pytest.raises(ValueError):
        set_manual_balance(conn, tomorrow, -10000, today)

    row_count = conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0]
    assert row_count == 0


def test_manual_balance_on_same_date_as_import_wins():
    conn = _connect_migrated()
    today = date(2026, 9, 23)
    conn.execute(
        "INSERT INTO balances (account, as_of, amount_cents, source) VALUES (?, ?, ?, 'import')",
        ("DE00", "2026-09-20", -40000),
    )
    conn.commit()

    set_manual_balance(conn, date(2026, 9, 20), -30000, today)

    assert current_balance(conn) == BalanceEntry(
        as_of=date(2026, 9, 20), amount_cents=-30000, source="manual"
    )


def test_newer_import_beats_older_manual_balance():
    conn = _connect_migrated()
    today = date(2026, 9, 23)
    set_manual_balance(conn, date(2026, 9, 10), -30000, today)
    conn.execute(
        "INSERT INTO balances (account, as_of, amount_cents, source) VALUES (?, ?, ?, 'import')",
        ("DE00", "2026-09-20", -50000),
    )
    conn.commit()

    assert current_balance(conn) == BalanceEntry(
        as_of=date(2026, 9, 20), amount_cents=-50000, source="import"
    )


def test_saving_manual_balance_twice_on_one_date_updates_it():
    conn = _connect_migrated()
    today = date(2026, 9, 23)
    set_manual_balance(conn, date(2026, 9, 20), -30000, today)
    set_manual_balance(conn, date(2026, 9, 20), -10000, today)

    assert current_balance(conn) == BalanceEntry(
        as_of=date(2026, 9, 20), amount_cents=-10000, source="manual"
    )
    row_count = conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0]
    assert row_count == 1


def test_current_balance_none_when_no_balances():
    conn = _connect_migrated()
    assert current_balance(conn) is None
