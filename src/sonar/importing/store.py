"""Store one uploaded bank export: the thin shell around the pure importers.

Re-imports are safe because every row is keyed by `(fingerprint, occurrence)`
and inserted with `INSERT OR IGNORE`, so rows already stored count as
duplicates instead of being added again (SPEC §4 Idempotency).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sonar.categorize import Rule
from sonar.categorizing import reapply_rules
from sonar.importing.dedup import NumberedTransaction, number_occurrences
from sonar.importing.importers import pick_importer
from sonar.transactions import ParsedBalance


@dataclass(frozen=True)
class ImportResult:
    """What the upload page reports for one file."""

    filename: str
    format: str
    added: int
    duplicates: int
    uncategorized: int


def import_file(
    conn: sqlite3.Connection,
    content: bytes,
    filename: str,
    rules: tuple[Rule, ...] = (),
) -> ImportResult:
    """Parse `content` with the matching importer and store its new rows and balance.

    Re-applies `rules` to every stored row afterwards (SPEC §5), so editing the
    rule set and re-importing categorizes rows that were already on file, not
    just the ones this file adds. Raises `UnknownFormatError` when no importer
    recognizes the file.
    """
    importer = pick_importer(content)
    numbered = number_occurrences(importer.parse(content))
    # parse_balance is optional: not every export format reports a balance.
    parse_balance = getattr(importer, "parse_balance", None)
    balance = parse_balance(content) if parse_balance else None

    # One transaction per file, so a failure part-way leaves nothing half-imported.
    with conn:
        inserted_ids = [
            row_id
            for row in numbered
            if (row_id := _insert_transaction(conn, importer.NAME, row)) is not None
        ]
        if balance is not None:
            _insert_balance(conn, balance)

    # Runs against the whole table, not just `inserted_ids`, so a rule change
    # also reclassifies rows stored by earlier imports.
    reapply_rules(conn, rules)

    return ImportResult(
        filename=filename,
        format=importer.NAME,
        added=len(inserted_ids),
        duplicates=len(numbered) - len(inserted_ids),
        uncategorized=_uncategorized_among(conn, inserted_ids),
    )


def _insert_transaction(
    conn: sqlite3.Connection, source: str, row: NumberedTransaction
) -> int | None:
    """Insert `row` unless its (fingerprint, occurrence) is stored; return its id if added."""
    tx = row.transaction
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source,
            tx.account,
            tx.booking_date.isoformat(),
            tx.value_date.isoformat(),
            tx.amount_cents,
            tx.currency,
            tx.counterparty,
            tx.purpose,
            tx.iban,
            tx.mandate_ref,
            tx.creditor_id,
            tx.raw_row,
            row.fingerprint,
            row.occurrence,
        ),
    )
    return cursor.lastrowid if cursor.rowcount == 1 else None


def _uncategorized_among(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Count how many of this file's newly inserted rows are still uncategorized."""
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    (count,) = conn.execute(
        f"SELECT COUNT(*) FROM transactions WHERE category IS NULL AND id IN ({placeholders})",
        ids,
    ).fetchone()
    return count


def _insert_balance(conn: sqlite3.Connection, balance: ParsedBalance) -> None:
    # The first import of a given (account, date) wins, so re-imports change nothing.
    conn.execute(
        "INSERT OR IGNORE INTO balances (account, as_of, amount_cents, source) "
        "VALUES (?, ?, ?, 'import')",
        (balance.account, balance.as_of.isoformat(), balance.amount_cents),
    )
