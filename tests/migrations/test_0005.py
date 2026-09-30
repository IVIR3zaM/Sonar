"""Tests for migration 0005: settings (salary day)."""

import sqlite3

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _insert_transaction(conn: sqlite3.Connection) -> None:
    """Insert a sample transaction from M1."""
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
            1,
        ),
    )


def _insert_import_balance(conn: sqlite3.Connection) -> None:
    """Insert a sample balance from M1."""
    conn.execute(
        """
        INSERT INTO balances (account, as_of, amount_cents, source)
        VALUES (?, ?, ?, ?)
        """,
        ("DE00000000000000000000", "2024-01-15", 500000, "import"),
    )


def _insert_recurring_payment(conn: sqlite3.Connection) -> int:
    """Insert a sample recurring payment from M3 and return its id."""
    payment_id = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked,
            schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("mandate:cred/ref", "Water", "Utilities", "active", "detected", 0, 0, None),
    ).lastrowid

    conn.execute(
        """
        INSERT INTO schedule_periods (
            payment_id, starts_on, until, amount_cents, interval_months, day
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (payment_id, "2024-01-15", None, 24000, 2, 15),
    )

    return payment_id


def _insert_debt(conn: sqlite3.Connection) -> None:
    """Insert a sample debt from M4."""
    conn.execute(
        """
        INSERT INTO debts (
            kind, name, rate_cents, match_field, match_value,
            total_cents, interval_months, first_payment_date, payments_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "installment",
            "Sofa",
            10000,
            "counterparty",
            "Furniture Store",
            120000,
            1,
            "2026-01-05",
            12,
        ),
    )


def test_valid_settings_insert():
    """Valid settings row with id=1, salary_day=26, overdraft_limit_cents=-50000."""
    conn = _connect_migrated()
    conn.execute(
        "INSERT INTO settings (id, salary_day, overdraft_limit_cents) VALUES (?, ?, ?)",
        (1, 26, -50000),
    )
    conn.commit()

    row = conn.execute("SELECT id, salary_day, overdraft_limit_cents FROM settings").fetchone()
    assert row is not None
    assert row[0] == 1
    assert row[1] == 26
    assert row[2] == -50000


@pytest.mark.parametrize(
    "invalid_id,salary_day",
    [
        (2, 26),  # id must be 1
    ],
    ids=["id_2"],
)
def test_invalid_id_raises(invalid_id: int, salary_day: int):
    """id must be 1; other values raise IntegrityError."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO settings (id, salary_day) VALUES (?, ?)",
            (invalid_id, salary_day),
        )
        conn.commit()


@pytest.mark.parametrize(
    "salary_day",
    [0, 32],
    ids=["salary_day_0", "salary_day_32"],
)
def test_invalid_salary_day_raises(salary_day: int):
    """salary_day must be between 1 and 31; other values raise IntegrityError."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO settings (id, salary_day) VALUES (?, ?)",
            (1, salary_day),
        )
        conn.commit()


def test_null_salary_day_raises():
    """salary_day cannot be NULL."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO settings (id, salary_day, overdraft_limit_cents) VALUES (?, ?, ?)",
            (1, None, -50000),
        )
        conn.commit()


@pytest.mark.parametrize(
    "overdraft_limit_cents",
    [-50000, 0, -1, -999999],
    ids=["overdraft_-50000", "overdraft_0", "overdraft_-1", "overdraft_-999999"],
)
def test_valid_overdraft_limit_insert(overdraft_limit_cents: int):
    """overdraft_limit_cents can be 0 or negative."""
    conn = _connect_migrated()
    conn.execute(
        "INSERT INTO settings (id, salary_day, overdraft_limit_cents) VALUES (?, ?, ?)",
        (1, 26, overdraft_limit_cents),
    )
    conn.commit()

    row = conn.execute("SELECT overdraft_limit_cents FROM settings").fetchone()
    assert row is not None
    assert row[0] == overdraft_limit_cents


def test_positive_overdraft_limit_raises():
    """overdraft_limit_cents must not be positive."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO settings (id, salary_day, overdraft_limit_cents) VALUES (?, ?, ?)",
            (1, 26, 1),
        )
        conn.commit()


def test_null_overdraft_limit_raises():
    """overdraft_limit_cents cannot be NULL."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO settings (id, salary_day, overdraft_limit_cents) VALUES (?, ?, ?)",
            (1, 26, None),
        )
        conn.commit()


def test_0001_0004_data_survives():
    """Transactions, balances, recurring payments and debts from M1-M4 survive M5 migration."""
    conn = _connect_migrated()
    _insert_transaction(conn)
    _insert_import_balance(conn)
    payment_id = _insert_recurring_payment(conn)
    _insert_debt(conn)
    conn.commit()
    # Hand-entered data from M1-M4 must survive every upgrade (SPEC §3).

    tx_row = conn.execute(
        """SELECT source, account, booking_date, amount_cents, counterparty,
           purpose FROM transactions"""
    ).fetchone()
    expected_tx = (
        "deutsche_bank_giro",
        "DE00000000000000000000",
        "2024-01-15",
        -1234,
        "Some Shop",
        "purchase",
    )
    assert tx_row == expected_tx

    balance_row = conn.execute(
        "SELECT account, as_of, amount_cents, source FROM balances"
    ).fetchone()
    assert balance_row is not None
    assert balance_row[0] == "DE00000000000000000000"
    assert balance_row[2] == 500000
    assert balance_row[3] == "import"

    payment_row = conn.execute(
        "SELECT id, name, status FROM recurring_payments WHERE id = ?",
        (payment_id,),
    ).fetchone()
    assert payment_row is not None
    assert payment_row[1] == "Water"
    assert payment_row[2] == "active"

    period_row = conn.execute(
        """SELECT payment_id, amount_cents, interval_months, day
           FROM schedule_periods WHERE payment_id = ?""",
        (payment_id,),
    ).fetchone()
    assert period_row is not None
    assert period_row[1] == 24000
    assert period_row[2] == 2
    assert period_row[3] == 15

    debt_row = conn.execute("SELECT kind, name, rate_cents FROM debts").fetchone()
    assert debt_row is not None
    assert debt_row[0] == "installment"
    assert debt_row[1] == "Sofa"
    assert debt_row[2] == 10000
