"""The one service layer between HTTP input and `taxonomy_store`.

Shared by the Categories page (N08, N09) and the JSON API (N17): both call
these functions and nothing in `taxonomy_store` directly, so validation and
error messages exist in exactly one place. Besides the re-apply function the
app's routes and the CLI share, this holds the category CRUD used by the
Categories page (N08): raw text input in, `TaxonomyError` (a friendly
`message` plus the input `field` it concerns) out, and every successful
write re-applies the stored rules and re-syncs detected payments in the same
call.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from sonar import spending_groups, taxonomy_store
from sonar.categorizing import reapply_rules, uncategorized_count
from sonar.money import parse_cents
from sonar.recurring import sync_detected
from sonar.taxonomy_store import (
    CategoryNotFound,  # noqa: F401 re-exported for callers
    RuleNotFound,  # noqa: F401 re-exported for callers
    load_stored_taxonomy,
)

# N02 group order: income and transfers first (not spending), then the three
# spending groups in the order the Monthly page shows them.
GROUP_ORDER = (
    spending_groups.INCOME,
    spending_groups.TRANSFER,
    spending_groups.FIXED,
    spending_groups.LIGHTS_ON,
    spending_groups.OCCASIONAL,
)

_CATEGORY_IN_USE = re.compile(r"^category '(?P<name>.*)' is used by (?P<count>\d+) rule\(s\)$")


class TaxonomyError(ValueError):
    """A category/rule input error with a friendly `message` and the `field` it concerns."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass(frozen=True)
class CategoryView:
    id: int
    name: str
    group: str
    group_label: str
    rule_count: int


@dataclass(frozen=True)
class RuleView:
    """A rule's fields as text, ready for the Rules table's chips and for JSON.

    Blank conditions are "" (not None) and `sign` is always "any"/"debit"/
    "credit", so both the page and the N17 API can render every field the
    same way without a None check.
    """

    id: int
    position: int
    category: str
    group: str
    counterparty: str
    counterparty_regex: str
    purpose: str
    purpose_regex: str
    sign: str
    iban: str
    creditor_id: str
    min_amount: str
    max_amount: str


def reapply_stored_taxonomy(conn: sqlite3.Connection, today: date) -> int:
    """Re-apply the DB's own rules and re-sync detected payments; return the uncategorized count."""
    taxonomy = load_stored_taxonomy(conn)
    reapply_rules(conn, taxonomy.rules)
    sync_detected(conn, taxonomy.categories, today)
    return uncategorized_count(conn)


def list_categories(conn: sqlite3.Connection) -> list[CategoryView]:
    """Categories in `GROUP_ORDER`, then id, ready for the Categories page and API."""
    position = {group: index for index, group in enumerate(GROUP_ORDER)}
    rows = sorted(taxonomy_store.list_categories(conn), key=lambda c: (position[c.type], c.id))
    return [
        CategoryView(
            id=row.id,
            name=row.name,
            group=row.type,
            group_label=spending_groups.LABELS[row.type],
            rule_count=row.rule_count,
        )
        for row in rows
    ]


def add_category(conn: sqlite3.Connection, today: date, name: str, group: str) -> int:
    name = name.strip()
    try:
        category_id = taxonomy_store.add_category(conn, name, group)
    except ValueError as error:
        raise _category_error(error, name) from None
    reapply_stored_taxonomy(conn, today)
    return category_id


def update_category(conn: sqlite3.Connection, today: date, id: int, name: str, group: str) -> None:
    name = name.strip()
    try:
        taxonomy_store.update_category(conn, id, name, group)
    except ValueError as error:
        raise _category_error(error, name) from None
    reapply_stored_taxonomy(conn, today)


def delete_category(conn: sqlite3.Connection, today: date, id: int) -> None:
    try:
        taxonomy_store.delete_category(conn, id)
    except ValueError as error:
        raise _category_error(error, None) from None
    reapply_stored_taxonomy(conn, today)


def _category_error(error: ValueError, name: str | None) -> TaxonomyError:
    # `taxonomy_store`'s ValueErrors are written for developers; translate the
    # ones the Categories page and API can trigger into a sentence naming the
    # field, so both surfaces show the same message (SPEC §12 Friendly errors).
    text = str(error)
    if "must not be blank" in text:
        return TaxonomyError("Name must not be blank.", "name")
    if "already exists" in text:
        return TaxonomyError(f'A category named "{name}" already exists.', "name")
    if "unknown category type" in text:
        return TaxonomyError(f"Group must be one of: {', '.join(GROUP_ORDER)}.", "group")
    in_use = _CATEGORY_IN_USE.match(text)
    if in_use:
        return TaxonomyError(
            f"{in_use['name']} is used by {in_use['count']} rules; move or delete them first.",
            None,
        )
    return TaxonomyError(text, None)


_BAD_REGEX = re.compile(r"has a bad regex in (?P<field>\w+)")

# The rule text fields carried through untouched (trimmed, blank -> None);
# amount and position get their own parsing since they change type.
_RULE_TEXT_FIELDS = (
    "category",
    "counterparty",
    "counterparty_regex",
    "purpose",
    "purpose_regex",
    "iban",
    "creditor_id",
)


def list_rules(conn: sqlite3.Connection) -> list[RuleView]:
    """Rules in position order, every field as text, ready for the Rules table and API."""
    category_types = dict(conn.execute("SELECT name, type FROM categories").fetchall())
    return [
        RuleView(
            id=rule.id,
            position=rule.position,
            category=rule.category,
            group=category_types.get(rule.category, ""),
            counterparty=rule.counterparty or "",
            counterparty_regex=rule.counterparty_regex or "",
            purpose=rule.purpose or "",
            purpose_regex=rule.purpose_regex or "",
            sign=rule.sign or "any",
            iban=rule.iban or "",
            creditor_id=rule.creditor_id or "",
            min_amount=_amount_text(rule.min_amount_cents),
            max_amount=_amount_text(rule.max_amount_cents),
        )
        for rule in taxonomy_store.list_rules(conn)
    ]


def add_rule(conn: sqlite3.Connection, today: date, fields: Mapping[str, str]) -> int:
    raw = _parse_rule_fields(fields)
    position = _parse_position(fields.get("position"))
    try:
        rule_id = taxonomy_store.add_rule(conn, raw, position)
    except ValueError as error:
        raise _rule_error(error, raw) from None
    reapply_stored_taxonomy(conn, today)
    return rule_id


def update_rule(conn: sqlite3.Connection, today: date, id: int, fields: Mapping[str, str]) -> None:
    raw = _parse_rule_fields(fields)
    position = _parse_position(fields.get("position"))
    try:
        taxonomy_store.update_rule(conn, id, raw, position)
    except ValueError as error:
        raise _rule_error(error, raw) from None
    reapply_stored_taxonomy(conn, today)


def delete_rule(conn: sqlite3.Connection, today: date, id: int) -> None:
    # RuleNotFound (a LookupError, not a ValueError) passes straight through.
    taxonomy_store.delete_rule(conn, id)
    reapply_stored_taxonomy(conn, today)


def move_rule(conn: sqlite3.Connection, today: date, id: int, position: str) -> None:
    parsed = _parse_position(position, required=True)
    taxonomy_store.move_rule(conn, id, parsed)
    reapply_stored_taxonomy(conn, today)


def _parse_rule_fields(fields: Mapping[str, str]) -> dict:
    """Raw rule-form text to `taxonomy_store.add_rule`'s `raw` mapping.

    Trims every text field (blank -> None); `sign` "any" also becomes None.
    Regex validity, the unknown-category and no-text-condition checks, and
    min > max are left to `taxonomy_store` (via `categorize.validate_rule`)
    and translated back to a friendly message by `_rule_error`.
    """

    def trimmed(key: str) -> str | None:
        value = (fields.get(key) or "").strip()
        return value or None

    raw = {key: trimmed(key) for key in _RULE_TEXT_FIELDS}
    sign = trimmed("sign")
    raw["sign"] = None if sign == "any" else sign
    raw["min_amount_cents"] = _parse_amount(fields.get("min_amount"), "min_amount")
    raw["max_amount_cents"] = _parse_amount(fields.get("max_amount"), "max_amount")
    return raw


def _parse_amount(text: str | None, field: str) -> int | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return parse_cents(text)
    except ValueError:
        raise TaxonomyError("Amount must be a number like 12.50.", field) from None


def _parse_position(text: str | None, *, required: bool = False) -> int | None:
    text = (text or "").strip()
    if not text:
        if required:
            raise TaxonomyError("Position must be a whole number from 1.", "position")
        return None
    if not text.isdigit() or int(text) < 1:
        raise TaxonomyError("Position must be a whole number from 1.", "position")
    return int(text)


def _amount_text(cents: int | None) -> str:
    if cents is None:
        return ""
    whole, remainder = divmod(cents, 100)
    return f"{whole}.{remainder:02d}"


def _rule_error(error: ValueError, raw: dict) -> TaxonomyError:
    # `categorize.validate_rule`'s ValueErrors are written for developers;
    # translate the ones the Rules card and API can trigger into a sentence
    # naming the field, so both surfaces show the same message.
    text = str(error)
    if "undefined category" in text:
        return TaxonomyError(f"Unknown category: {raw.get('category')}.", "category")
    if "has no text condition" in text:
        return TaxonomyError("Enter a counterparty or purpose text or regex.", None)
    bad_regex = _BAD_REGEX.search(text)
    if bad_regex:
        field = bad_regex["field"]
        label = "Counterparty" if field == "counterparty_regex" else "Purpose"
        return TaxonomyError(f"{label} regex is not a valid pattern.", field)
    if "min_amount_cents above max_amount_cents" in text:
        return TaxonomyError("Minimum amount must not be above maximum amount.", "min_amount")
    return TaxonomyError(text, None)
