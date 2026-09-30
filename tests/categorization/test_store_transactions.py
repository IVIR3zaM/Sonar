"""Tests for the categorization DB shell: reapply_rules and uncategorized queries (SPEC §5)."""

import sqlite3

import pytest

from sonar.categorization.rules import Rule
from sonar.categorization.store import (
    reapply_rules,
    transactions_with_category,
    uncategorized_count,
    uncategorized_transactions,
)
from sonar.db import MIGRATIONS_DIR, apply_migrations

RENT_RULE = Rule(category="Rent", counterparty="Landlord")


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _insert(
    conn: sqlite3.Connection,
    *,
    fingerprint: str,
    counterparty: str = "",
    purpose: str = "",
    amount_cents: int = -1000,
) -> None:
    """Insert one row directly by SQL, bypassing import_file (that's T7's job)."""
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence
        ) VALUES (
            'test', 'acc', '2026-01-01', '2026-01-01', ?, 'EUR',
            ?, ?, NULL, NULL, NULL, 'raw', ?, 1
        )
        """,
        (amount_cents, counterparty, purpose, fingerprint),
    )


def test_reapply_rules_sets_category_on_matching_rows(conn: sqlite3.Connection) -> None:
    _insert(conn, fingerprint="a", counterparty="My Landlord GmbH")
    _insert(conn, fingerprint="b", counterparty="Someone Else")

    changed = reapply_rules(conn, (RENT_RULE,))

    rows = conn.execute(
        "SELECT counterparty, category FROM transactions ORDER BY fingerprint"
    ).fetchall()
    assert rows == [("My Landlord GmbH", "Rent"), ("Someone Else", None)]
    assert changed == 1


def test_reapply_rules_resets_category_when_rule_is_removed(conn: sqlite3.Connection) -> None:
    _insert(conn, fingerprint="a", counterparty="My Landlord GmbH")
    reapply_rules(conn, (RENT_RULE,))

    changed = reapply_rules(conn, ())

    (category,) = conn.execute(
        "SELECT category FROM transactions WHERE fingerprint = 'a'"
    ).fetchone()
    assert category is None
    assert changed == 1


def test_second_reapply_with_unchanged_rules_changes_nothing(conn: sqlite3.Connection) -> None:
    _insert(conn, fingerprint="a", counterparty="My Landlord GmbH")
    reapply_rules(conn, (RENT_RULE,))

    changed = reapply_rules(conn, (RENT_RULE,))

    assert changed == 0


def test_uncategorized_count_and_list_only_include_null_rows(conn: sqlite3.Connection) -> None:
    _insert(conn, fingerprint="a", counterparty="My Landlord GmbH", purpose="rent")
    _insert(conn, fingerprint="b", counterparty="Someone Else", purpose="misc", amount_cents=-500)
    reapply_rules(conn, (RENT_RULE,))

    assert uncategorized_count(conn) == 1
    txs = uncategorized_transactions(conn)
    assert [tx.counterparty for tx in txs] == ["Someone Else"]
    assert txs[0].purpose == "misc"
    assert txs[0].amount_cents == -500


def test_transactions_with_category_pairs_every_row_with_its_category(
    conn: sqlite3.Connection,
) -> None:
    _insert(conn, fingerprint="a", counterparty="My Landlord GmbH", purpose="rent")
    _insert(conn, fingerprint="b", counterparty="Someone Else", purpose="misc", amount_cents=-500)
    reapply_rules(conn, (RENT_RULE,))

    pairs = transactions_with_category(conn)

    by_counterparty = {tx.counterparty: category for tx, category in pairs}
    assert by_counterparty == {"My Landlord GmbH": "Rent", "Someone Else": None}
