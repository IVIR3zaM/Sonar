"""Tests for migration 0001: the `transactions` and `balances` tables."""

import sqlite3

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _insert_transaction(conn: sqlite3.Connection, occurrence: int = 1) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "deutsche_bank_giro",
            "DE00000000000000000000",
            "2024-01-15",
            "2024-01-15",
            -1234,
            "EUR",
            "Some Shop",
            "purchase",
            None,
            None,
            None,
            "raw;row;text",
            "abc123",
            occurrence,
        ),
    )


def test_duplicate_fingerprint_and_occurrence_raises_integrity_error():
    conn = _connect_migrated()
    _insert_transaction(conn, occurrence=1)
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        _insert_transaction(conn, occurrence=1)


def test_same_fingerprint_different_occurrence_is_allowed():
    conn = _connect_migrated()
    _insert_transaction(conn, occurrence=1)
    _insert_transaction(conn, occurrence=2)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert count == 2


def test_balances_accepts_a_manual_row():
    conn = _connect_migrated()

    conn.execute(
        "INSERT INTO balances (account, as_of, amount_cents, source) VALUES (?, ?, ?, ?)",
        ("DE00000000000000000000", "2024-01-31", 500000, "manual"),
    )
    conn.commit()

    row = conn.execute("SELECT account, as_of, amount_cents, source FROM balances").fetchone()
    assert row == ("DE00000000000000000000", "2024-01-31", 500000, "manual")


def test_balances_rejects_unknown_source():
    conn = _connect_migrated()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO balances (account, as_of, amount_cents, source) VALUES (?, ?, ?, ?)",
            ("DE00000000000000000000", "2024-01-31", 500000, "bogus"),
        )


def test_duplicate_balance_for_same_account_date_and_source_raises():
    conn = _connect_migrated()
    conn.execute(
        "INSERT INTO balances (account, as_of, amount_cents, source) VALUES (?, ?, ?, ?)",
        ("DE00000000000000000000", "2024-01-31", 500000, "manual"),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO balances (account, as_of, amount_cents, source) VALUES (?, ?, ?, ?)",
            ("DE00000000000000000000", "2024-01-31", 999999, "manual"),
        )
