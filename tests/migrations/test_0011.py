"""Tests for migration 0011: debts.match_field accepts 'purpose' (SPEC §13 Debt purpose match)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations

COLUMNS = "SELECT * FROM debts ORDER BY id"
INSERT_LOAN = """
    INSERT INTO debts (
        id, kind, name, rate_cents, match_field, match_value,
        balance_cents, balance_as_of, interest_bp
    ) VALUES (?, 'loan', ?, 5000, ?, ?, 90000, ?, 350)
"""


def _migrated_before_0011(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0011":
            shutil.copy(path, migrations)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations)
    return conn, migrations


def _table_info(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("PRAGMA table_info(debts)").fetchall()


def test_existing_debts_keep_every_value_and_id(tmp_path):
    conn, migrations = _migrated_before_0011(tmp_path)
    conn.execute(
        """
        INSERT INTO debts (
            id, kind, name, rate_cents, match_field, match_value,
            total_cents, interval_months, first_payment_date, payments_count
        ) VALUES (7, 'installment', 'Sofa', 10000, 'counterparty', 'Sofa Store',
                  120000, 1, '2026-01-05', 12)
        """
    )
    conn.execute(INSERT_LOAN, (42, "Car loan", "mandate", "M-1", "2026-06-30"))
    conn.commit()
    before = conn.execute(COLUMNS).fetchall()
    columns_before = _table_info(conn)
    shutil.copy(MIGRATIONS_DIR / "0011_debts_purpose_match.sql", migrations)

    apply_migrations(conn, migrations)

    assert conn.execute(COLUMNS).fetchall() == before
    assert [row[0] for row in before] == [7, 42]
    assert _table_info(conn) == columns_before


def test_purpose_rows_insert_but_other_match_fields_and_broken_loans_do_not():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)

    conn.execute(INSERT_LOAN, (1, "Order", "purpose", "305-7936467-3301953", "2026-06-30"))

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(INSERT_LOAN, (2, "Bad", "iban", "DE00", "2026-06-30"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(INSERT_LOAN, (3, "No date", "purpose", "x", None))
