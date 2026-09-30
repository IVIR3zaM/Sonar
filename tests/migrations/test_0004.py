"""Tests for migration 0004: installments and loans."""

import sqlite3
from pathlib import Path

import pytest

from sonar.db import apply_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"


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

    # Add a schedule period
    conn.execute(
        """
        INSERT INTO schedule_periods (
            payment_id, starts_on, until, amount_cents, interval_months, day
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (payment_id, "2024-01-15", None, 24000, 2, 15),
    )

    return payment_id


def test_valid_installment_insert():
    """Valid installment with all required fields can be inserted."""
    conn = _connect_migrated()
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
    conn.commit()

    # Verify it was inserted
    row = conn.execute("SELECT id, kind, name FROM debts").fetchone()
    assert row is not None
    assert row[1] == "installment"
    assert row[2] == "Sofa"


def test_valid_loan_insert_with_interest():
    """Valid loan with interest_bp can be inserted."""
    conn = _connect_migrated()
    conn.execute(
        """
        INSERT INTO debts (
            kind, name, rate_cents, match_field, match_value,
            balance_cents, balance_as_of, interest_bp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "loan",
            "Car Loan",
            100000,
            "mandate",
            "M-1",
            500000,
            "2026-06-30",
            600,
        ),
    )
    conn.commit()

    # Verify it was inserted
    row = conn.execute("SELECT id, kind, name FROM debts").fetchone()
    assert row is not None
    assert row[1] == "loan"
    assert row[2] == "Car Loan"


def test_valid_loan_insert_without_interest():
    """Valid loan without interest_bp (linear) can be inserted."""
    conn = _connect_migrated()
    conn.execute(
        """
        INSERT INTO debts (
            kind, name, rate_cents, match_field, match_value,
            balance_cents, balance_as_of
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "loan",
            "Personal Loan",
            100000,
            "counterparty",
            "Bank ABC",
            200000,
            "2026-09-01",
        ),
    )
    conn.commit()

    # Verify it was inserted
    row = conn.execute("SELECT id, kind, name, interest_bp FROM debts").fetchone()
    assert row is not None
    assert row[1] == "loan"
    assert row[2] == "Personal Loan"
    assert row[3] is None


@pytest.mark.parametrize(
    "invalid_kind",
    ["lease", "credit", "mortgage"],
    ids=["kind_lease", "kind_credit", "kind_mortgage"],
)
def test_invalid_kind_raises(invalid_kind: str):
    """Invalid kind value raises IntegrityError."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO debts (
                kind, name, rate_cents, match_field, match_value,
                total_cents, interval_months, first_payment_date, payments_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invalid_kind,
                "Sofa",
                10000,
                "counterparty",
                "Store",
                120000,
                1,
                "2026-01-05",
                12,
            ),
        )
        conn.commit()


def test_installment_without_payments_count_raises():
    """Installment without payments_count raises IntegrityError."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
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
                "Store",
                120000,
                1,
                "2026-01-05",
                None,
            ),
        )
        conn.commit()


def test_loan_with_total_cents_set_raises():
    """Loan with total_cents set raises IntegrityError."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO debts (
                kind, name, rate_cents, match_field, match_value,
                balance_cents, balance_as_of, total_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "loan",
                "Car Loan",
                100000,
                "mandate",
                "M-1",
                500000,
                "2026-06-30",
                600000,
            ),
        )
        conn.commit()


def test_loan_without_balance_as_of_raises():
    """Loan without balance_as_of raises IntegrityError."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO debts (
                kind, name, rate_cents, match_field, match_value,
                balance_cents, balance_as_of
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "loan",
                "Car Loan",
                100000,
                "mandate",
                "M-1",
                500000,
                None,
            ),
        )
        conn.commit()


def test_rate_cents_zero_raises():
    """rate_cents must be > 0."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
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
                0,
                "counterparty",
                "Store",
                120000,
                1,
                "2026-01-05",
                12,
            ),
        )
        conn.commit()


def test_invalid_match_field_raises():
    """match_field must be 'counterparty' or 'mandate'."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
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
                "iban",
                "DE00000000000000000000",
                120000,
                1,
                "2026-01-05",
                12,
            ),
        )
        conn.commit()


def test_empty_name_raises():
    """name cannot be empty."""
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO debts (
                kind, name, rate_cents, match_field, match_value,
                total_cents, interval_months, first_payment_date, payments_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "installment",
                "",
                10000,
                "counterparty",
                "Store",
                120000,
                1,
                "2026-01-05",
                12,
            ),
        )
        conn.commit()


def test_0001_0003_data_survives():
    """Transactions and recurring payments from M1/M2/M3 survive M4 migration."""
    conn = _connect_migrated()
    _insert_transaction(conn)
    payment_id = _insert_recurring_payment(conn)
    conn.commit()

    # Verify transaction survives
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

    # Verify recurring payment survives
    payment_row = conn.execute(
        "SELECT id, name, status FROM recurring_payments WHERE id = ?",
        (payment_id,),
    ).fetchone()
    assert payment_row is not None
    assert payment_row[1] == "Water"
    assert payment_row[2] == "active"

    # Verify schedule period survives
    period_row = conn.execute(
        """SELECT payment_id, amount_cents, interval_months, day
           FROM schedule_periods WHERE payment_id = ?""",
        (payment_id,),
    ).fetchone()
    assert period_row is not None
    assert period_row[1] == 24000
    assert period_row[2] == 2
    assert period_row[3] == 15
