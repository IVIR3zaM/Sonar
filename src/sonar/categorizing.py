"""DB shell for categorization (SPEC §5): re-applying rules to stored rows.

`categorize.py` holds the pure rule engine over `ParsedTransaction`. This
module is the thin shell around it: it reads stored transaction rows,
recomputes each one's category, and writes back only the rows whose category
actually changed, so a rule-set edit (or removal) takes effect on every
existing row, not just newly imported ones.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from sonar.categorize import Rule, categorize
from sonar.transactions import ParsedTransaction

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
