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
from dataclasses import dataclass
from datetime import date

from sonar import spending_groups, taxonomy_store
from sonar.categorizing import reapply_rules, uncategorized_count
from sonar.recurring import sync_detected
from sonar.taxonomy_store import (
    CategoryNotFound,  # noqa: F401 re-exported for callers
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
