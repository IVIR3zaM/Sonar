"""Tests for migration 0006: categories and category_rules (SPEC §5, §13)."""

import sqlite3
from pathlib import Path

import pytest

from sonar.db import apply_migrations
from sonar.spending_groups import TYPES

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"

EXPECTED_SEED = {
    "Salary": "income",
    "Other income": "income",
    "Own transfers": "transfer",
    "Housing": "fixed",
    "Utilities": "fixed",
    "Insurance": "fixed",
    "Phone & Internet": "fixed",
    "Subscriptions": "fixed",
    "Loans & Installments": "fixed",
    "Groceries": "lights_on",
    "Transport": "lights_on",
    "Shopping": "lights_on",
    "Dining": "occasional",
    "Health": "occasional",
    "Fees & Taxes": "occasional",
    "Education": "occasional",
    "Donations": "occasional",
}


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_seed_has_17_generic_categories_no_rules():
    conn = _connect_migrated()
    rows = conn.execute("SELECT name, type FROM categories").fetchall()
    assert len(rows) == 17
    assert dict(rows) == EXPECTED_SEED
    assert all(t in TYPES for _, t in rows)
    assert conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] == 0


def test_category_name_must_be_unique_and_non_blank():
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO categories (name, type) VALUES ('Salary', 'income')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO categories (name, type) VALUES ('', 'income')")


def test_category_type_check():
    conn = _connect_migrated()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO categories (name, type) VALUES ('Fake', 'variable')")


def test_rule_sign_check():
    conn = _connect_migrated()
    category_id = conn.execute("SELECT id FROM categories WHERE name = 'Housing'").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO category_rules (position, category_id, counterparty, sign) "
            "VALUES (1, ?, 'Fake Landlord', 'both')",
            (category_id,),
        )
