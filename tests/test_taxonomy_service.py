"""Tests for taxonomy_service (SPEC §5, §13): the DB re-apply and category CRUD
shared by the Categories page (N08) and the JSON API (N17)."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.taxonomy_service import (
    CategoryNotFound,
    RuleNotFound,
    TaxonomyError,
    add_category,
    add_rule,
    delete_category,
    delete_rule,
    list_categories,
    list_rules,
    move_rule,
    reapply_stored_taxonomy,
    update_category,
    update_rule,
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


def _fresh_db(db_path: Path) -> None:
    # The 0006 migration's generic seed (Groceries, Housing, Donations, ...),
    # unlike tests.seed.seed which replaces the taxonomy with a given TOML.
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
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


def test_add_rule_trims_text_maps_any_sign_to_none_and_parses_amounts(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        add_rule(
            conn,
            TODAY,
            {
                "category": "Groceries",
                "counterparty": "  Fake Market  ",
                "counterparty_regex": "",
                "purpose": "",
                "purpose_regex": "",
                "sign": "any",
                "iban": "",
                "creditor_id": "",
                "min_amount": "10.00",
                "max_amount": "50.00",
                "position": "",
            },
        )

        [rule] = list_rules(conn)
        assert rule.category == "Groceries"
        assert rule.counterparty == "Fake Market"
        assert rule.counterparty_regex == ""
        assert rule.sign == "any"
        assert rule.min_amount == "10.00"
        assert rule.max_amount == "50.00"
        assert rule.position == 1
    finally:
        conn.close()


def test_add_rule_reapplies_and_categorizes_a_matching_row(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(
            conn, fingerprint="m1", booking_date="2026-09-05", counterparty="Fake Market Filiale 3"
        )

        add_rule(conn, TODAY, {"category": "Groceries", "counterparty": "fake market"})

        category = conn.execute(
            "SELECT category FROM transactions WHERE fingerprint = 'm1'"
        ).fetchone()[0]
        assert category == "Groceries"
    finally:
        conn.close()


def test_add_rule_with_no_text_condition_raises_and_leaves_rules_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(TaxonomyError) as exc_info:
            add_rule(conn, TODAY, {"category": "Groceries"})

        assert exc_info.value.field is None
        assert exc_info.value.message == "Enter a counterparty or purpose text or regex."
        assert list_rules(conn) == []
    finally:
        conn.close()


def test_add_rule_with_bad_counterparty_regex_raises_and_leaves_rules_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(TaxonomyError) as exc_info:
            add_rule(conn, TODAY, {"category": "Groceries", "counterparty_regex": "("})

        assert exc_info.value.field == "counterparty_regex"
        assert exc_info.value.message == "Counterparty regex is not a valid pattern."
        assert list_rules(conn) == []
    finally:
        conn.close()


def test_add_rule_with_bad_purpose_regex_raises_and_leaves_rules_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(TaxonomyError) as exc_info:
            add_rule(conn, TODAY, {"category": "Groceries", "purpose_regex": "("})

        assert exc_info.value.field == "purpose_regex"
        assert exc_info.value.message == "Purpose regex is not a valid pattern."
        assert list_rules(conn) == []
    finally:
        conn.close()


def test_add_rule_with_unknown_category_raises_and_leaves_rules_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(TaxonomyError) as exc_info:
            add_rule(conn, TODAY, {"category": "Nope", "counterparty": "Fake Market"})

        assert exc_info.value.field == "category"
        assert exc_info.value.message == "Unknown category: Nope."
        assert list_rules(conn) == []
    finally:
        conn.close()


def test_add_rule_with_unparsable_amount_raises_and_leaves_rules_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(TaxonomyError) as exc_info:
            add_rule(
                conn,
                TODAY,
                {"category": "Groceries", "counterparty": "Fake Market", "min_amount": "abc"},
            )

        assert exc_info.value.field == "min_amount"
        assert exc_info.value.message == "Amount must be a number like 12.50."
        assert list_rules(conn) == []
    finally:
        conn.close()


def test_add_rule_with_min_above_max_raises_and_leaves_rules_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(TaxonomyError) as exc_info:
            add_rule(
                conn,
                TODAY,
                {
                    "category": "Groceries",
                    "counterparty": "Fake Market",
                    "min_amount": "50.00",
                    "max_amount": "10.00",
                },
            )

        assert exc_info.value.field == "min_amount"
        assert exc_info.value.message == "Minimum amount must not be above maximum amount."
        assert list_rules(conn) == []
    finally:
        conn.close()


def test_add_rule_with_bad_position_raises_and_leaves_rules_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(TaxonomyError) as exc_info:
            add_rule(
                conn,
                TODAY,
                {"category": "Groceries", "counterparty": "Fake Market", "position": "0"},
            )

        assert exc_info.value.field == "position"
        assert exc_info.value.message == "Position must be a whole number from 1."
        assert list_rules(conn) == []
    finally:
        conn.close()


def test_list_rules_returns_positions_1_to_n_in_order(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        add_rule(conn, TODAY, {"category": "Groceries", "counterparty": "Fake Market"})
        add_rule(conn, TODAY, {"category": "Housing", "counterparty": "Fake Landlord"})
        add_rule(conn, TODAY, {"category": "Donations", "counterparty": "Fake Charity"})

        rules = list_rules(conn)
        assert [r.position for r in rules] == [1, 2, 3]
        assert [r.category for r in rules] == ["Groceries", "Housing", "Donations"]
    finally:
        conn.close()


def test_move_rule_reorders_and_first_match_still_wins(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        add_rule(conn, TODAY, {"category": "Groceries", "counterparty": "Fake Market"})
        second_id = add_rule(conn, TODAY, {"category": "Donations", "counterparty": "Fake Market"})

        move_rule(conn, TODAY, second_id, "1")

        rules = list_rules(conn)
        assert [r.category for r in rules] == ["Donations", "Groceries"]
        assert rules[0].id == second_id
    finally:
        conn.close()


def test_move_rule_blank_position_raises(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rule_id = add_rule(conn, TODAY, {"category": "Groceries", "counterparty": "Fake Market"})

        with pytest.raises(TaxonomyError) as exc_info:
            move_rule(conn, TODAY, rule_id, "")

        assert exc_info.value.field == "position"
    finally:
        conn.close()


def test_update_rule_changes_category(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rule_id = add_rule(conn, TODAY, {"category": "Groceries", "counterparty": "Fake Market"})

        update_rule(conn, TODAY, rule_id, {"category": "Donations", "counterparty": "Fake Market"})

        [rule] = list_rules(conn)
        assert rule.category == "Donations"
    finally:
        conn.close()


def test_delete_rule_removes_it_and_renumbers(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        first_id = add_rule(conn, TODAY, {"category": "Groceries", "counterparty": "Fake Market"})
        second_id = add_rule(conn, TODAY, {"category": "Donations", "counterparty": "Fake Charity"})

        delete_rule(conn, TODAY, first_id)

        rules = list_rules(conn)
        assert [r.id for r in rules] == [second_id]
        assert rules[0].position == 1
    finally:
        conn.close()


def test_update_rule_unknown_id_raises_rule_not_found(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(RuleNotFound):
            update_rule(
                conn, TODAY, 999_999, {"category": "Groceries", "counterparty": "Fake Market"}
            )
    finally:
        conn.close()


def test_delete_rule_unknown_id_raises_rule_not_found(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(RuleNotFound):
            delete_rule(conn, TODAY, 999_999)
    finally:
        conn.close()


def test_move_rule_unknown_id_raises_rule_not_found(tmp_path):
    db_path = tmp_path / "t.db"
    _fresh_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(RuleNotFound):
            move_rule(conn, TODAY, 999_999, "1")
    finally:
        conn.close()
