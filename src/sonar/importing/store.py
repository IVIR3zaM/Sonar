"""Store imported bookings: the thin shell around the pure importers and matcher.

Re-imports are safe because every CSV row is keyed by `(fingerprint, occurrence)`
and every synced row by its bank `entry_reference`, so rows already stored count
as duplicates instead of being added again (SPEC §4 Idempotency). A booking that
arrives both in a CSV and from the bank sync is stored once (SPEC §13 Bank sync).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from sonar.categorization.rules import Rule
from sonar.categorization.store import reapply_rules
from sonar.importing.dedup import NumberedTransaction, number_occurrences
from sonar.importing.importers import pick_importer
from sonar.importing.match import pair
from sonar.transactions import ParsedBalance, ParsedTransaction

# A synced row merges only into a CSV row; a CSV row only into a synced row not yet merged.
_UNSYNCED = "entry_reference IS NULL"
_SYNCED_UNMERGED = "entry_reference IS NOT NULL AND merged = 0"


@dataclass(frozen=True)
class ImportResult:
    """What the upload page reports for one file."""

    filename: str
    format: str
    added: int
    duplicates: int
    uncategorized: int


@dataclass(frozen=True)
class ImportCounts:
    """What one batch of rows did to the stored transactions."""

    added: int
    duplicates: int
    uncategorized: int


@dataclass(frozen=True)
class _StoredRow:
    id: int
    account: str
    booking_date: date
    amount_cents: int
    counterparty: str
    purpose: str


def import_file(
    conn: sqlite3.Connection,
    content: bytes,
    filename: str,
    rules: tuple[Rule, ...] = (),
) -> ImportResult:
    """Parse `content` with the matching importer and store its new rows and balance.

    Raises `UnknownFormatError` when no importer recognizes the file.
    """
    importer = pick_importer(content)
    # parse_balance is optional: not every export format reports a balance.
    parse_balance = getattr(importer, "parse_balance", None)
    balance = parse_balance(content) if parse_balance else None

    counts = import_rows(conn, importer.NAME, importer.parse(content), balance, rules)

    return ImportResult(
        filename=filename,
        format=importer.NAME,
        added=counts.added,
        duplicates=counts.duplicates,
        uncategorized=counts.uncategorized,
    )


def import_rows(
    conn: sqlite3.Connection,
    source: str,
    transactions: Iterable[ParsedTransaction],
    balance: ParsedBalance | None = None,
    rules: tuple[Rule, ...] = (),
) -> ImportCounts:
    """Store the new rows of one batch and its balance, merging the other source's matches.

    Re-applies `rules` to every stored row afterwards (SPEC §5), so editing the
    rule set and re-importing categorizes rows that were already on file, not
    just the ones this batch adds.
    """
    transactions = list(transactions)
    synced = [tx for tx in transactions if tx.entry_reference is not None]
    exported = number_occurrences(tx for tx in transactions if tx.entry_reference is None)

    # One transaction per batch, so a failure part-way leaves nothing half-imported.
    with conn:
        inserted_ids = _store_synced(conn, source, synced) + _store_exported(conn, source, exported)
        if balance is not None:
            _insert_balance(conn, balance)

    # Runs against the whole table, not just `inserted_ids`, so a rule change
    # also reclassifies rows stored by earlier imports.
    reapply_rules(conn, rules)

    return ImportCounts(
        added=len(inserted_ids),
        duplicates=len(transactions) - len(inserted_ids),
        uncategorized=_uncategorized_among(conn, inserted_ids),
    )


def _store_synced(conn: sqlite3.Connection, source: str, txs: list[ParsedTransaction]) -> list[int]:
    """Store synced rows whose entry reference is new; a CSV match only gains the reference."""
    known = _stored_entry_references(conn, txs)
    fresh = []
    for tx in txs:
        if tx.entry_reference not in known:
            known.add(tx.entry_reference)
            fresh.append(tx)

    candidates = _candidates(conn, fresh, _UNSYNCED)
    pairs = pair(fresh, candidates)
    for i, s in pairs.items():
        # The first-stored row keeps its data; the reference makes refetches duplicates.
        conn.execute(
            "UPDATE transactions SET entry_reference = ?, merged = 1 WHERE id = ?",
            (fresh[i].entry_reference, candidates[s].id),
        )
    return _insert_all(
        conn,
        source,
        [(tx, _synced_fingerprint(tx), 1) for i, tx in enumerate(fresh) if i not in pairs],
    )


def _store_exported(
    conn: sqlite3.Connection, source: str, numbered: list[NumberedTransaction]
) -> list[int]:
    """Store CSV rows not on file; a synced match takes the CSV's fuller details and key."""
    fresh = [row for row in numbered if not _is_stored(conn, row)]
    txs = [row.transaction for row in fresh]

    candidates = _candidates(conn, txs, _SYNCED_UNMERGED)
    pairs = pair(txs, candidates)
    for i, s in pairs.items():
        row = fresh[i]
        conn.execute(
            """
            UPDATE transactions
            SET purpose = ?, mandate_ref = ?, creditor_id = ?,
                fingerprint = ?, occurrence = ?, merged = 1
            WHERE id = ?
            """,
            (
                row.transaction.purpose,
                row.transaction.mandate_ref,
                row.transaction.creditor_id,
                row.fingerprint,
                row.occurrence,
                candidates[s].id,
            ),
        )
    return _insert_all(
        conn,
        source,
        [
            (row.transaction, row.fingerprint, row.occurrence)
            for i, row in enumerate(fresh)
            if i not in pairs
        ],
    )


def _stored_entry_references(
    conn: sqlite3.Connection, txs: Sequence[ParsedTransaction]
) -> set[str | None]:
    references = [tx.entry_reference for tx in txs]
    if not references:
        return set()
    placeholders = ",".join("?" * len(references))
    rows = conn.execute(
        f"SELECT entry_reference FROM transactions WHERE entry_reference IN ({placeholders})",
        references,
    )
    return {reference for (reference,) in rows}


def _is_stored(conn: sqlite3.Connection, row: NumberedTransaction) -> bool:
    found = conn.execute(
        "SELECT 1 FROM transactions WHERE fingerprint = ? AND occurrence = ?",
        (row.fingerprint, row.occurrence),
    ).fetchone()
    return found is not None


def _candidates(
    conn: sqlite3.Connection, txs: Sequence[ParsedTransaction], condition: str
) -> list[_StoredRow]:
    """Load the stored rows `txs` could merge into: only their accounts and booking dates."""
    if not txs:
        return []
    accounts = sorted({tx.account for tx in txs})
    dates = sorted({tx.booking_date.isoformat() for tx in txs})
    rows = conn.execute(
        f"""
        SELECT id, account, booking_date, amount_cents, counterparty, purpose
        FROM transactions
        WHERE {condition}
          AND account IN ({",".join("?" * len(accounts))})
          AND booking_date IN ({",".join("?" * len(dates))})
        ORDER BY id
        """,
        [*accounts, *dates],
    )
    return [
        _StoredRow(
            id=row_id,
            account=account,
            booking_date=date.fromisoformat(booking_date),
            amount_cents=amount_cents,
            counterparty=counterparty or "",
            purpose=purpose or "",
        )
        for row_id, account, booking_date, amount_cents, counterparty, purpose in rows
    ]


def _synced_fingerprint(tx: ParsedTransaction) -> str:
    # Keyed on the bank's reference, so two identical same-day bookings stay distinct.
    encoded = json.dumps(["enable-banking", tx.account, tx.entry_reference], ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _insert_all(
    conn: sqlite3.Connection,
    source: str,
    rows: list[tuple[ParsedTransaction, str, int]],
) -> list[int]:
    return [
        row_id
        for tx, fingerprint, occurrence in rows
        if (row_id := _insert_transaction(conn, source, tx, fingerprint, occurrence)) is not None
    ]


def _insert_transaction(
    conn: sqlite3.Connection,
    source: str,
    tx: ParsedTransaction,
    fingerprint: str,
    occurrence: int,
) -> int | None:
    """Insert `tx` unless its (fingerprint, occurrence) is stored; return its id if added."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, entry_reference
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            fingerprint,
            occurrence,
            tx.entry_reference,
        ),
    )
    return cursor.lastrowid if cursor.rowcount == 1 else None


def _uncategorized_among(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Count how many of this batch's newly inserted rows are still uncategorized."""
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
