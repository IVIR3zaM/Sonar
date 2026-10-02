"""Tests for store.py: DB CRUD for categories and rules (SPEC §5, §13)."""

import sqlite3

import pytest

from sonar.categorization.rules import Taxonomy, parse_taxonomy
from sonar.categorization.store import (
    CategoryNotFound,
    RuleNotFound,
    add_category,
    add_rule,
    delete_category,
    delete_rule,
    list_categories,
    list_rules,
    load_stored_taxonomy,
    move_rule,
    replace_taxonomy,
    update_category,
    update_rule,
)
from sonar.db import MIGRATIONS_DIR, apply_migrations

FAKE_TOML = """
[[category]]
name = "Groceries"
type = "lights_on"

[[category]]
name = "Salary"
type = "income"

[[rule]]
category = "Groceries"
counterparty = "Fake Market"
sign = "debit"
iban = "DE89370400440532013000"
min_amount_cents = 100
max_amount_cents = 50000

[[rule]]
category = "Salary"
purpose_regex = "wages"
creditor_id = "DE00FAKE00000000000"
sign = "credit"
"""


def _connect_migrated() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _seed_fake_taxonomy(conn: sqlite3.Connection) -> Taxonomy:
    taxonomy = parse_taxonomy(FAKE_TOML)
    replace_taxonomy(conn, taxonomy)
    return taxonomy


def test_fresh_db_loads_17_seed_categories_no_rules():
    conn = _connect_migrated()
    taxonomy = load_stored_taxonomy(conn)
    assert len(taxonomy.categories) == 17
    assert taxonomy.categories["Groceries"] == "lights_on"
    assert taxonomy.rules == ()


def test_replace_taxonomy_round_trips():
    conn = _connect_migrated()
    taxonomy = _seed_fake_taxonomy(conn)
    loaded = load_stored_taxonomy(conn)
    assert loaded.categories == taxonomy.categories
    assert len(loaded.rules) == len(taxonomy.rules)
    for stored, original in zip(loaded.rules, taxonomy.rules, strict=True):
        assert stored.category == original.category
        assert stored.counterparty == original.counterparty
        assert stored.sign == original.sign
        assert stored.iban == original.iban
        assert stored.creditor_id == original.creditor_id
        assert stored.min_amount_cents == original.min_amount_cents
        assert stored.max_amount_cents == original.max_amount_cents
        if original.purpose_regex is None:
            assert stored.purpose_regex is None
        else:
            assert stored.purpose_regex.pattern == original.purpose_regex.pattern


def test_add_rule_at_position_1_puts_it_first_and_renumbers():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    add_rule(conn, {"category": "Salary", "counterparty": "Fake Employer"}, position=1)
    rules = list_rules(conn)
    assert [r.position for r in rules] == [1, 2, 3]
    assert rules[0].counterparty == "Fake Employer"
    assert rules[1].counterparty == "Fake Market"


def test_move_last_to_1_and_delete_keep_positions_contiguous():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    rules = list_rules(conn)
    last_id = rules[-1].id
    move_rule(conn, last_id, 1)
    rules = list_rules(conn)
    assert [r.position for r in rules] == [1, 2]
    assert rules[0].id == last_id

    delete_rule(conn, rules[0].id)
    rules = list_rules(conn)
    assert [r.position for r in rules] == [1]


def test_add_rule_unknown_category_raises_and_leaves_tables_unchanged():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    before_categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    before_rules = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
    with pytest.raises(ValueError):
        add_rule(conn, {"category": "Nonexistent", "counterparty": "Fake Shop"})
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == before_categories
    assert conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] == before_rules


def test_add_rule_no_text_condition_raises_and_leaves_tables_unchanged():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    before_rules = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
    with pytest.raises(ValueError):
        add_rule(conn, {"category": "Groceries", "sign": "debit"})
    assert conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] == before_rules


def test_add_rule_bad_regex_raises_and_leaves_tables_unchanged():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    before_rules = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
    with pytest.raises(ValueError):
        add_rule(conn, {"category": "Groceries", "counterparty_regex": "("})
    assert conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] == before_rules


def test_rename_category_cascades_to_transaction_and_recurring_payment():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, amount_cents, currency, counterparty,
            purpose, raw_row, fingerprint, occurrence, category
        ) VALUES ('fake', 'DE00', '2024-01-01', -100, 'EUR', 'Fake Market', 'x', 'raw',
                  'fp1', 1, 'Groceries')
        """
    )
    conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source, name_locked, schedule_locked
        ) VALUES ('fake-key', 'Fake Market Sub', 'Groceries', 'active', 'detected', 0, 0)
        """
    )
    conn.commit()

    category_id = conn.execute("SELECT id FROM categories WHERE name = 'Groceries'").fetchone()[0]
    update_category(conn, category_id, "Food", "lights_on")

    assert conn.execute("SELECT category FROM transactions").fetchone()[0] == "Food"
    assert conn.execute("SELECT category FROM recurring_payments").fetchone()[0] == "Food"


def test_delete_category_with_rules_raises():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    category_id = conn.execute("SELECT id FROM categories WHERE name = 'Groceries'").fetchone()[0]
    before_categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    before_rules = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
    with pytest.raises(ValueError):
        delete_category(conn, category_id)
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == before_categories
    assert conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] == before_rules
    assert (
        conn.execute("SELECT id FROM categories WHERE id = ?", (category_id,)).fetchone()[0]
        == category_id
    )


def test_delete_unused_category_clears_name_from_transactions():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, amount_cents, currency, counterparty,
            purpose, raw_row, fingerprint, occurrence, category
        ) VALUES ('fake', 'DE00', '2024-01-01', -100, 'EUR', 'Fake Shop', 'x', 'raw',
                  'fp2', 1, 'Salary')
        """
    )
    conn.commit()
    salary_id = add_category(conn, "Fake Unused", "income")
    conn.execute("UPDATE transactions SET category = 'Fake Unused' WHERE fingerprint = 'fp2'")
    conn.commit()

    delete_category(conn, salary_id)
    assert conn.execute("SELECT category FROM transactions").fetchone()[0] is None
    assert conn.execute("SELECT id FROM categories WHERE name = 'Fake Unused'").fetchone() is None


def test_duplicate_and_blank_category_names_raise():
    conn = _connect_migrated()
    with pytest.raises(ValueError):
        add_category(conn, "Groceries", "lights_on")
    with pytest.raises(ValueError):
        add_category(conn, "", "lights_on")
    with pytest.raises(ValueError):
        add_category(conn, "   ", "lights_on")


def test_unknown_ids_raise_not_found_errors():
    conn = _connect_migrated()
    with pytest.raises(CategoryNotFound):
        update_category(conn, 9999, "Fake", "lights_on")
    with pytest.raises(CategoryNotFound):
        delete_category(conn, 9999)
    with pytest.raises(RuleNotFound):
        update_rule(conn, 9999, {"category": "Groceries", "counterparty": "Fake"})
    with pytest.raises(RuleNotFound):
        delete_rule(conn, 9999)
    with pytest.raises(RuleNotFound):
        move_rule(conn, 9999, 1)


def test_list_categories_reports_rule_counts():
    conn = _connect_migrated()
    _seed_fake_taxonomy(conn)
    by_name = {c.name: c.rule_count for c in list_categories(conn)}
    assert by_name["Groceries"] == 1
    assert by_name["Salary"] == 1

    add_category(conn, "Fake Empty", "fixed")
    by_name = {c.name: c.rule_count for c in list_categories(conn)}
    assert by_name["Fake Empty"] == 0


def test_add_category_stores_the_debt_flag_and_defaults_to_false():
    conn = _connect_migrated()
    add_category(conn, "Fake Loan", "fixed", debt=True)
    add_category(conn, "Fake Rent", "fixed")

    by_name = {c.name: c.debt for c in list_categories(conn)}

    assert by_name["Fake Loan"] is True
    assert by_name["Fake Rent"] is False


def test_debt_flag_on_a_non_fixed_category_raises_and_leaves_the_table_unchanged():
    conn = _connect_migrated()
    before = list_categories(conn)

    with pytest.raises(ValueError, match="debt"):
        add_category(conn, "Fake Pets", "occasional", debt=True)

    assert list_categories(conn) == before


def test_update_category_keeps_the_flag_when_debt_is_none():
    conn = _connect_migrated()
    loans = next(c for c in list_categories(conn) if c.debt)

    update_category(conn, loans.id, "Fake Credits", "fixed")

    assert next(c for c in list_categories(conn) if c.id == loans.id).debt is True


def test_update_category_sets_and_clears_the_flag():
    conn = _connect_migrated()
    housing = next(c for c in list_categories(conn) if c.name == "Housing")

    update_category(conn, housing.id, "Housing", "fixed", debt=True)
    assert next(c for c in list_categories(conn) if c.id == housing.id).debt is True

    update_category(conn, housing.id, "Housing", "fixed", debt=False)
    assert next(c for c in list_categories(conn) if c.id == housing.id).debt is False


def test_regrouping_a_flagged_category_raises_unless_the_flag_is_cleared():
    conn = _connect_migrated()
    loans = next(c for c in list_categories(conn) if c.debt)

    with pytest.raises(ValueError, match="debt"):
        update_category(conn, loans.id, loans.name, "occasional")
    with pytest.raises(ValueError, match="debt"):
        update_category(conn, loans.id, loans.name, "occasional", debt=True)

    update_category(conn, loans.id, loans.name, "occasional", debt=False)
    updated = next(c for c in list_categories(conn) if c.id == loans.id)
    assert (updated.type, updated.debt) == ("occasional", False)


def test_replace_taxonomy_keeps_the_flag_of_a_surviving_fixed_category():
    conn = _connect_migrated()
    add_category(conn, "Fake Regrouped", "fixed", debt=True)
    toml = """
[[category]]
name = "Loans & Installments"
type = "fixed"

[[category]]
name = "Fake Regrouped"
type = "occasional"

[[category]]
name = "Fake New"
type = "fixed"

[[category]]
name = "Housing"
type = "fixed"
"""

    replace_taxonomy(conn, parse_taxonomy(toml))

    assert {c.name: c.debt for c in list_categories(conn)} == {
        "Loans & Installments": True,
        "Fake Regrouped": False,
        "Fake New": False,
        "Housing": False,
    }
