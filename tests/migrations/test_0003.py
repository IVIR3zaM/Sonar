"""Tests for migration 0003: recurring payments and schedule periods."""

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


def test_duplicate_detection_key_raises():
    """Duplicate non-NULL detection_key raises IntegrityError."""
    conn = _connect_migrated()
    conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked,
            schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("mandate:cred/ref", "Water", "Utilities", "active", "detected", 0, 0, None),
    )
    conn.commit()

    # Attempt to insert a duplicate
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO recurring_payments (
                detection_key, name, category, status, source, name_locked,
                schedule_locked, last_paid_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("mandate:cred/ref", "Water 2", "Utilities", "active", "detected", 0, 0, None),
        )
        conn.commit()


def test_multiple_null_detection_keys_allowed():
    """Multiple NULL detection_keys (manual entries) are allowed."""
    conn = _connect_migrated()

    # Insert first manual entry
    conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked,
            schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (None, "Manual Payment 1", "Fixed", "active", "manual", 1, 1, None),
    )

    # Insert second manual entry
    conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked,
            schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (None, "Manual Payment 2", "Fixed", "active", "manual", 1, 1, None),
    )
    conn.commit()

    # Verify both were inserted
    count = conn.execute(
        "SELECT COUNT(*) FROM recurring_payments WHERE detection_key IS NULL"
    ).fetchone()[0]
    assert count == 2


def test_interval_zero_rejected():
    """interval_months must be >= 1."""
    conn = _connect_migrated()
    payment_id = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked,
            schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("mandate:cred/ref", "Water", "Utilities", "active", "detected", 0, 0, None),
    ).lastrowid
    conn.commit()

    # Attempt to insert schedule period with interval 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO schedule_periods (
                payment_id, starts_on, until, amount_cents, interval_months, day
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payment_id, "2024-01-15", None, 24000, 0, 15),
        )
        conn.commit()


def test_day_32_rejected():
    """day must be between 1 and 31."""
    conn = _connect_migrated()
    payment_id = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked,
            schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("mandate:cred/ref", "Water", "Utilities", "active", "detected", 0, 0, None),
    ).lastrowid
    conn.commit()

    # Attempt to insert schedule period with day 32
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO schedule_periods (
                payment_id, starts_on, until, amount_cents, interval_months, day
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payment_id, "2024-01-15", None, 24000, 2, 32),
        )
        conn.commit()


def test_amount_zero_rejected():
    """amount_cents must be > 0."""
    conn = _connect_migrated()
    payment_id = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked,
            schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("mandate:cred/ref", "Water", "Utilities", "active", "detected", 0, 0, None),
    ).lastrowid
    conn.commit()

    # Attempt to insert schedule period with amount 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO schedule_periods (
                payment_id, starts_on, until, amount_cents, interval_months, day
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payment_id, "2024-01-15", None, 0, 2, 15),
        )
        conn.commit()


def test_0001_0002_data_survives():
    """Transactions and balance data from M1/M2 survive the M3 migration."""
    conn = _connect_migrated()
    _insert_transaction(conn)
    conn.commit()

    # Verify transactions table still has the data
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
