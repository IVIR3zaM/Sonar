"""Tests for taxonomy_service (SPEC §5, §13): the DB re-apply and category CRUD
shared by the Categories page (N08) and the JSON API (N17)."""

import sqlite3
from datetime import date

import pytest

from sonar.taxonomy_service import (
    CategoryNotFound,
    TaxonomyError,
    add_category,
    delete_category,
    list_categories,
    reapply_stored_taxonomy,
    update_category,
)
from tests.seed import seed

TODAY = date(2026, 9, 23)

DINING_RULE_TOML = """
[[category]]
name = "Dining"
type = "occasional"

[[rule]]
category = "Dining"
counterparty = "Fake Diner"
"""

FITNESS_TOML = """
[[category]]
name = "Fitness"
type = "fixed"

[[rule]]
category = "Fitness"
counterparty = "Fake Gym"
"""


def _insert(
    conn: sqlite3.Connection, *, fingerprint: str, booking_date: str, counterparty: str
) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', ?, ?, -5000, 'EUR', ?, '', NULL, NULL, NULL, 'raw', ?, 1, NULL
        )
        """,
        (booking_date, booking_date, counterparty, fingerprint),
    )
    conn.commit()


def test_reapply_categorizes_matching_rows_and_detects_a_monthly_fixed_series(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, FITNESS_TOML)

    conn = sqlite3.connect(db_path)
    try:
        for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
            _insert(conn, fingerprint=f"gym{i}", booking_date=booking_date, counterparty="Fake Gym")
        _insert(conn, fingerprint="shop1", booking_date="2026-09-05", counterparty="Random Shop")

        uncategorized = reapply_stored_taxonomy(conn, TODAY)

        assert uncategorized == 1
        categories = dict(conn.execute("SELECT fingerprint, category FROM transactions").fetchall())
        assert categories["gym0"] == categories["gym1"] == categories["gym2"] == "Fitness"
        assert categories["shop1"] is None
        (payment_count,) = conn.execute("SELECT COUNT(*) FROM recurring_payments").fetchone()
        assert payment_count == 1
    finally:
        conn.close()


def _category_id(conn: sqlite3.Connection, name: str) -> int:
    return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def test_add_category_trims_name(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    conn = sqlite3.connect(db_path)
    try:
        add_category(conn, TODAY, "  Pets  ", "occasional")

        names = {c.name: c.group for c in list_categories(conn)}
        assert names["Pets"] == "occasional"
    finally:
        conn.close()


def test_add_category_blank_name_raises_and_leaves_table_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    conn = sqlite3.connect(db_path)
    try:
        before = list_categories(conn)

        with pytest.raises(TaxonomyError) as exc_info:
            add_category(conn, TODAY, "   ", "occasional")

        assert exc_info.value.field == "name"
        assert exc_info.value.message == "Name must not be blank."
        assert list_categories(conn) == before
    finally:
        conn.close()


def test_add_category_duplicate_name_raises_and_leaves_table_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, DINING_RULE_TOML)
    conn = sqlite3.connect(db_path)
    try:
        before = list_categories(conn)

        with pytest.raises(TaxonomyError) as exc_info:
            add_category(conn, TODAY, "Dining", "occasional")

        assert exc_info.value.field == "name"
        assert list_categories(conn) == before
    finally:
        conn.close()


def test_add_category_unknown_group_raises_and_leaves_table_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    conn = sqlite3.connect(db_path)
    try:
        before = list_categories(conn)

        with pytest.raises(TaxonomyError) as exc_info:
            add_category(conn, TODAY, "Pets", "bogus")

        assert exc_info.value.field == "group"
        assert list_categories(conn) == before
    finally:
        conn.close()


def test_delete_category_with_a_rule_raises_and_leaves_tables_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, DINING_RULE_TOML)
    conn = sqlite3.connect(db_path)
    try:
        dining_id = _category_id(conn, "Dining")
        before = list_categories(conn)

        with pytest.raises(TaxonomyError) as exc_info:
            delete_category(conn, TODAY, dining_id)

        assert exc_info.value.field is None
        assert list_categories(conn) == before
    finally:
        conn.close()


def test_unknown_category_id_raises_not_found(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(CategoryNotFound):
            update_category(conn, TODAY, 999_999, "Pets", "occasional")
        with pytest.raises(CategoryNotFound):
            delete_category(conn, TODAY, 999_999)
    finally:
        conn.close()


def test_successful_update_reapplies_and_drops_detection_on_group_change(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, FITNESS_TOML)
    conn = sqlite3.connect(db_path)
    try:
        for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
            _insert(conn, fingerprint=f"gym{i}", booking_date=booking_date, counterparty="Fake Gym")
        reapply_stored_taxonomy(conn, TODAY)
        (payment_count,) = conn.execute("SELECT COUNT(*) FROM recurring_payments").fetchone()
        assert payment_count == 1

        fitness_id = _category_id(conn, "Fitness")
        update_category(conn, TODAY, fitness_id, "Fitness", "occasional")

        # occasional is excluded from recurring detection (spending_groups.py),
        # so the re-apply the update runs must drop the detected payment.
        (payment_count,) = conn.execute("SELECT COUNT(*) FROM recurring_payments").fetchone()
        assert payment_count == 0
    finally:
        conn.close()
