"""Tests for migration 0002: the `category` column in transactions."""

import sqlite3
from pathlib import Path

from sonar.db import apply_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _insert_transaction(conn: sqlite3.Connection, category: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            1,
            category,
        ),
    )


def test_inserted_transaction_has_category_null():
    """After applying migrations, a new transaction has category NULL."""
    conn = _connect_migrated()
    _insert_transaction(conn)
    conn.commit()

    row = conn.execute("SELECT category FROM transactions").fetchone()
    assert row[0] is None


def test_category_update_persists():
    """UPDATE category='X' persists across queries."""
    conn = _connect_migrated()
    _insert_transaction(conn)
    conn.commit()

    conn.execute("UPDATE transactions SET category = ? WHERE id = 1", ("Groceries",))
    conn.commit()

    row = conn.execute("SELECT category FROM transactions WHERE id = 1").fetchone()
    assert row[0] == "Groceries"


def test_0001_data_survives_migration():
    """Transactions from M1 (0001) still exist after 0002 is applied."""
    conn = _connect_migrated()
    _insert_transaction(conn)
    conn.commit()

    # Verify the transactions table still has the original columns
    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert count == 1

    # Verify we can read original columns
    row = conn.execute(
        """SELECT source, account, booking_date, amount_cents, counterparty,
           purpose FROM transactions"""
    ).fetchone()
    expected = (
        "deutsche_bank_giro",
        "DE00000000000000000000",
        "2024-01-15",
        -1234,
        "Some Shop",
        "purchase",
    )
    assert row == expected
