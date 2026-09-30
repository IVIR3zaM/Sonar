"""DB shell for categorization (SPEC §5, §13 Categorization config): categories, rules, re-applying.

`rules.py` holds the pure parsing, validation and matching; this module
stores that shape in `categories` and `category_rules` (0006_categories.sql)
and gives the Categories page and API their CRUD. Rule writes go through
`rules.validate_rule` so the DB accepts exactly what the TOML importer
accepts. Rule `position` is kept contiguous (1..n) after every add, delete or
move, since rules are tried in that order and the first match wins.

It also reads stored transaction rows, recomputes each one's category and
writes back only the rows whose category changed, so a rule-set edit takes
effect on every existing row, not just newly imported ones.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.categorization import groups
from sonar.categorization.rules import Rule, Taxonomy, categorize, validate_rule
from sonar.transactions import ParsedTransaction

_RULE_COLUMNS = (
    "counterparty, counterparty_regex, purpose, purpose_regex, "
    "sign, iban, creditor_id, min_amount_cents, max_amount_cents"
)


class CategoryNotFound(LookupError):
    """Raised by update/delete when `id` has no matching category row."""


class RuleNotFound(LookupError):
    """Raised by update/delete/move when `id` has no matching rule row."""


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    type: str
    rule_count: int


@dataclass(frozen=True)
class StoredRule:
    id: int
    position: int
    category_id: int
    category: str
    counterparty: str | None
    counterparty_regex: str | None
    purpose: str | None
    purpose_regex: str | None
    sign: str | None
    iban: str | None
    creditor_id: str | None
    min_amount_cents: int | None
    max_amount_cents: int | None


def load_stored_taxonomy(conn: sqlite3.Connection) -> Taxonomy:
    """Categories in id order, rules by position, ready for `rules.match_rule`."""
    categories = dict(conn.execute("SELECT name, type FROM categories ORDER BY id").fetchall())
    rows = conn.execute(
        f"""
        SELECT c.name, {_qualify(_RULE_COLUMNS, "r")}
        FROM category_rules r JOIN categories c ON c.id = r.category_id
        ORDER BY r.position
        """
    ).fetchall()
    rules = tuple(
        Rule(
            category=category,
            counterparty=counterparty,
            counterparty_regex=_compile(counterparty_regex),
            purpose=purpose,
            purpose_regex=_compile(purpose_regex),
            sign=sign,
            iban=iban,
            creditor_id=creditor_id,
            min_amount_cents=min_amount_cents,
            max_amount_cents=max_amount_cents,
        )
        for (
            category,
            counterparty,
            counterparty_regex,
            purpose,
            purpose_regex,
            sign,
            iban,
            creditor_id,
            min_amount_cents,
            max_amount_cents,
        ) in rows
    )
    return Taxonomy(categories=categories, rules=rules)


def replace_taxonomy(conn: sqlite3.Connection, taxonomy: Taxonomy) -> None:
    """Delete and rewrite both tables in one transaction (the CLI import path)."""
    with conn:
        conn.execute("DELETE FROM category_rules")
        conn.execute("DELETE FROM categories")
        category_ids = {
            name: conn.execute(
                "INSERT INTO categories (name, type) VALUES (?, ?)", (name, category_type)
            ).lastrowid
            for name, category_type in taxonomy.categories.items()
        }
        for position, rule in enumerate(taxonomy.rules, start=1):
            conn.execute(
                f"INSERT INTO category_rules (position, category_id, {_RULE_COLUMNS}) "
                f"VALUES (?, ?, {_placeholders(9)})",
                (position, category_ids[rule.category], *_rule_values(rule)),
            )


def list_categories(conn: sqlite3.Connection) -> list[Category]:
    rows = conn.execute(
        """
        SELECT c.id, c.name, c.type, COUNT(r.id)
        FROM categories c LEFT JOIN category_rules r ON r.category_id = c.id
        GROUP BY c.id ORDER BY c.id
        """
    ).fetchall()
    return [Category(id=i, name=name, type=t, rule_count=n) for i, name, t, n in rows]


def add_category(conn: sqlite3.Connection, name: str, type: str) -> int:
    _validate_category(name, type)
    with conn:
        _require_name_available(conn, name)
        return conn.execute(
            "INSERT INTO categories (name, type) VALUES (?, ?)", (name, type)
        ).lastrowid


def update_category(conn: sqlite3.Connection, id: int, name: str, type: str) -> None:
    _validate_category(name, type)
    with conn:
        old_name = _existing_category_name(conn, id)
        _require_name_available(conn, name, exclude_id=id)
        conn.execute("UPDATE categories SET name = ?, type = ? WHERE id = ?", (name, type, id))
        if name != old_name:
            conn.execute(
                "UPDATE transactions SET category = ? WHERE category = ?", (name, old_name)
            )
            conn.execute(
                "UPDATE recurring_payments SET category = ? WHERE category = ?", (name, old_name)
            )


def delete_category(conn: sqlite3.Connection, id: int) -> None:
    with conn:
        name = _existing_category_name(conn, id)
        rule_count = conn.execute(
            "SELECT COUNT(*) FROM category_rules WHERE category_id = ?", (id,)
        ).fetchone()[0]
        if rule_count:
            raise ValueError(f"category {name!r} is used by {rule_count} rule(s)")
        conn.execute("DELETE FROM categories WHERE id = ?", (id,))
        conn.execute("UPDATE transactions SET category = NULL WHERE category = ?", (name,))
        conn.execute("UPDATE recurring_payments SET category = NULL WHERE category = ?", (name,))


def list_rules(conn: sqlite3.Connection) -> list[StoredRule]:
    rows = conn.execute(
        f"""
        SELECT r.id, r.position, r.category_id, c.name, {_qualify(_RULE_COLUMNS, "r")}
        FROM category_rules r JOIN categories c ON c.id = r.category_id
        ORDER BY r.position
        """
    ).fetchall()
    return [StoredRule(*row) for row in rows]


def add_rule(conn: sqlite3.Connection, raw: dict, position: int | None = None) -> int:
    rule = validate_rule(raw, _category_types(conn))
    with conn:
        category_id = _category_id(conn, rule.category)
        count = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
        position = count + 1 if position is None else max(1, min(position, count + 1))
        conn.execute(
            "UPDATE category_rules SET position = position + 1 WHERE position >= ?", (position,)
        )
        return conn.execute(
            f"INSERT INTO category_rules (position, category_id, {_RULE_COLUMNS}) "
            f"VALUES (?, ?, {_placeholders(9)})",
            (position, category_id, *_rule_values(rule)),
        ).lastrowid


def update_rule(conn: sqlite3.Connection, id: int, raw: dict, position: int | None = None) -> None:
    rule = validate_rule(raw, _category_types(conn))
    with conn:
        if conn.execute("SELECT 1 FROM category_rules WHERE id = ?", (id,)).fetchone() is None:
            raise RuleNotFound(id)
        category_id = _category_id(conn, rule.category)
        conn.execute(
            "UPDATE category_rules SET category_id = ?, "
            + ", ".join(f"{col.strip()} = ?" for col in _RULE_COLUMNS.split(","))
            + " WHERE id = ?",
            (category_id, *_rule_values(rule), id),
        )
        if position is not None:
            _move_rule(conn, id, position)


def delete_rule(conn: sqlite3.Connection, id: int) -> None:
    with conn:
        row = conn.execute("SELECT position FROM category_rules WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise RuleNotFound(id)
        conn.execute("DELETE FROM category_rules WHERE id = ?", (id,))
        conn.execute(
            "UPDATE category_rules SET position = position - 1 WHERE position > ?", (row[0],)
        )


def move_rule(conn: sqlite3.Connection, id: int, position: int) -> None:
    with conn:
        if conn.execute("SELECT 1 FROM category_rules WHERE id = ?", (id,)).fetchone() is None:
            raise RuleNotFound(id)
        _move_rule(conn, id, position)


def _move_rule(conn: sqlite3.Connection, id: int, new_position: int) -> None:
    """Shift the rules between the old and new spot; caller holds the transaction."""
    count = conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0]
    new_position = max(1, min(new_position, count))
    current_position = conn.execute(
        "SELECT position FROM category_rules WHERE id = ?", (id,)
    ).fetchone()[0]
    if new_position == current_position:
        return
    if new_position > current_position:
        conn.execute(
            "UPDATE category_rules SET position = position - 1 "
            "WHERE position > ? AND position <= ?",
            (current_position, new_position),
        )
    else:
        conn.execute(
            "UPDATE category_rules SET position = position + 1 "
            "WHERE position >= ? AND position < ?",
            (new_position, current_position),
        )
    conn.execute("UPDATE category_rules SET position = ? WHERE id = ?", (new_position, id))


def _validate_category(name: str, type: str) -> None:
    if not name or not name.strip():
        raise ValueError("category name must not be blank")
    if type not in groups.TYPES:
        raise ValueError(f"unknown category type {type!r}")


def _require_name_available(
    conn: sqlite3.Connection, name: str, exclude_id: int | None = None
) -> None:
    query = "SELECT 1 FROM categories WHERE name = ?"
    params: tuple = (name,)
    if exclude_id is not None:
        query += " AND id != ?"
        params = (name, exclude_id)
    if conn.execute(query, params).fetchone() is not None:
        raise ValueError(f"category name {name!r} already exists")


def _existing_category_name(conn: sqlite3.Connection, id: int) -> str:
    row = conn.execute("SELECT name FROM categories WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise CategoryNotFound(id)
    return row[0]


def _category_types(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT name, type FROM categories").fetchall())


def _category_id(conn: sqlite3.Connection, name: str) -> int:
    return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def _rule_values(rule: Rule) -> tuple:
    return (
        rule.counterparty,
        rule.counterparty_regex.pattern if rule.counterparty_regex else None,
        rule.purpose,
        rule.purpose_regex.pattern if rule.purpose_regex else None,
        rule.sign,
        rule.iban,
        rule.creditor_id,
        rule.min_amount_cents,
        rule.max_amount_cents,
    )


def _compile(text: str | None) -> re.Pattern[str] | None:
    return re.compile(text, re.IGNORECASE) if text else None


def _qualify(columns: str, alias: str) -> str:
    return ", ".join(f"{alias}.{col.strip()}" for col in columns.split(","))


def _placeholders(n: int) -> str:
    return ", ".join(["?"] * n)


# `category` must stay last: `_transaction_from_row` ignores it and
# `reapply_rules` reads it as `row[-1]` to detect no-op updates.
_COLUMNS = (
    "id, account, booking_date, value_date, amount_cents, currency, "
    "counterparty, purpose, raw_row, iban, mandate_ref, creditor_id, category"
)


def reapply_rules(conn: sqlite3.Connection, rules: tuple[Rule, ...]) -> int:
    """Recompute `category` for every stored transaction; return rows changed.

    Runs as one transaction, so a rule set is applied to the whole table
    atomically instead of leaving some rows on an old rule set if something
    fails partway through.
    """
    changed = 0
    with conn:
        rows = conn.execute(f"SELECT {_COLUMNS} FROM transactions").fetchall()
        for row in rows:
            tx_id, current_category = row[0], row[-1]
            new_category = categorize(_transaction_from_row(row), rules)
            if new_category != current_category:
                conn.execute(
                    "UPDATE transactions SET category = ? WHERE id = ?",
                    (new_category, tx_id),
                )
                changed += 1
    return changed


def uncategorized_count(conn: sqlite3.Connection) -> int:
    (count,) = conn.execute("SELECT COUNT(*) FROM transactions WHERE category IS NULL").fetchone()
    return count


def uncategorized_transactions(conn: sqlite3.Connection) -> list[ParsedTransaction]:
    """Rebuild every uncategorized row as a `ParsedTransaction`, e.g. for the export."""
    rows = conn.execute(f"SELECT {_COLUMNS} FROM transactions WHERE category IS NULL").fetchall()
    return [_transaction_from_row(row) for row in rows]


def transactions_with_category(
    conn: sqlite3.Connection,
) -> list[tuple[ParsedTransaction, str | None]]:
    """Every stored transaction paired with its category, for recurring-payment detection."""
    rows = conn.execute(f"SELECT {_COLUMNS} FROM transactions").fetchall()
    return [(_transaction_from_row(row), row[-1]) for row in rows]


def _transaction_from_row(row: tuple) -> ParsedTransaction:
    (
        _id,
        account,
        booking_date,
        value_date,
        amount_cents,
        currency,
        counterparty,
        purpose,
        raw_row,
        iban,
        mandate_ref,
        creditor_id,
        _category,
    ) = row
    booking = date.fromisoformat(booking_date)
    return ParsedTransaction(
        account=account,
        booking_date=booking,
        # A missing value_date (some exports omit it) falls back to the
        # booking date rather than making the field optional everywhere.
        value_date=date.fromisoformat(value_date) if value_date else booking,
        amount_cents=amount_cents,
        currency=currency,
        counterparty=counterparty or "",
        purpose=purpose or "",
        raw_row=raw_row,
        iban=iban,
        mandate_ref=mandate_ref,
        creditor_id=creditor_id,
    )
