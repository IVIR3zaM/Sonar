"""Tests for migration 0008: categories.debt (SPEC §13 Debt categories)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations

LOANS = "Loans & Installments"


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _migrated_before_0008(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0008":
            shutil.copy(path, migrations)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations)
    return conn, migrations


def test_seeded_loans_category_is_flagged_and_no_other():
    conn = _connect_migrated()

    flagged = conn.execute("SELECT name FROM categories WHERE debt = 1").fetchall()

    assert flagged == [(LOANS,)]


def test_debt_defaults_to_zero_on_insert():
    conn = _connect_migrated()
    conn.execute("INSERT INTO categories (name, type) VALUES ('Extra', 'fixed')")

    assert conn.execute("SELECT debt FROM categories WHERE name = 'Extra'").fetchone() == (0,)


def test_debt_other_than_zero_or_one_is_rejected():
    conn = _connect_migrated()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO categories (name, type, debt) VALUES ('Extra', 'fixed', 2)")


def test_renamed_loans_category_gets_no_flag(tmp_path):
    conn, migrations = _migrated_before_0008(tmp_path)
    conn.execute("UPDATE categories SET name = 'Credits' WHERE name = ?", (LOANS,))
    conn.commit()
    shutil.copy(MIGRATIONS_DIR / "0008_category_debt.sql", migrations)

    apply_migrations(conn, migrations)

    assert conn.execute("SELECT COUNT(*) FROM categories WHERE debt = 1").fetchone() == (0,)


def test_regrouped_loans_category_gets_no_flag(tmp_path):
    conn, migrations = _migrated_before_0008(tmp_path)
    conn.execute("UPDATE categories SET type = 'occasional' WHERE name = ?", (LOANS,))
    conn.commit()
    shutil.copy(MIGRATIONS_DIR / "0008_category_debt.sql", migrations)

    apply_migrations(conn, migrations)

    assert conn.execute("SELECT COUNT(*) FROM categories WHERE debt = 1").fetchone() == (0,)
