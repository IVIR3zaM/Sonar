"""Bank storage (SPEC §13 Bank sync): the connection, its last sync, the pending authorization
and the synced balance."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from sonar.banking.consent import BankConnection, NewConnection
from sonar.transactions import ParsedBalance


def load_connection(conn: sqlite3.Connection) -> BankConnection | None:
    row = conn.execute(
        """
        SELECT session_id, account_uid, iban_last4, consent_valid_until, connected_at,
               last_sync_at, last_sync_status, last_sync_added, last_sync_error
        FROM bank_connection WHERE id = 1
        """
    ).fetchone()
    if row is None:
        return None
    session_id, account_uid, iban_last4, valid_until, connected_at, *last_sync = row
    last_sync_at, status, added, error = last_sync
    return BankConnection(
        session_id=session_id,
        account_uid=account_uid,
        iban_last4=iban_last4,
        consent_valid_until=_parse(valid_until),
        connected_at=_parse(connected_at),
        last_sync_at=_parse(last_sync_at) if last_sync_at else None,
        last_sync_status=status,
        last_sync_added=added,
        last_sync_error=error,
    )


def save_connection(conn: sqlite3.Connection, new: NewConnection) -> None:
    """Upsert the connection: new session fields, last-sync fields kept."""
    with conn:
        conn.execute(
            """
            INSERT INTO bank_connection
                (id, session_id, account_uid, iban_last4, consent_valid_until, connected_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                account_uid = excluded.account_uid,
                iban_last4 = excluded.iban_last4,
                consent_valid_until = excluded.consent_valid_until,
                connected_at = excluded.connected_at
            """,
            (
                new.session_id,
                new.account_uid,
                new.iban_last4,
                _format(new.consent_valid_until),
                _format(new.connected_at),
            ),
        )


def record_sync_ok(conn: sqlite3.Connection, at: datetime, added: int) -> None:
    _record_sync(conn, at, "ok", added, None)


def record_sync_error(conn: sqlite3.Connection, at: datetime, message: str) -> None:
    """Record a failed sync; `message` is the client's fixed-shape text, never a secret."""
    _record_sync(conn, at, "error", None, message)


def _record_sync(
    conn: sqlite3.Connection, at: datetime, status: str, added: int | None, error: str | None
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE bank_connection
            SET last_sync_at = ?, last_sync_status = ?, last_sync_added = ?, last_sync_error = ?
            WHERE id = 1
            """,
            (_format(at), status, added, error),
        )


def latest_account(conn: sqlite3.Connection, source: str) -> str | None:
    """The account of the latest-booked stored row from `source`, if any."""
    row = conn.execute(
        "SELECT account FROM transactions WHERE source = ? ORDER BY booking_date DESC, id DESC",
        (source,),
    ).fetchone()
    return row[0] if row else None


def upsert_balance(conn: sqlite3.Connection, balance: ParsedBalance) -> None:
    """Store the synced balance; a later sync on the same day replaces it."""
    with conn:
        conn.execute(
            """
            INSERT INTO balances (account, as_of, amount_cents, source)
            VALUES (?, ?, ?, 'import')
            ON CONFLICT(account, as_of, source) DO UPDATE SET amount_cents = excluded.amount_cents
            """,
            (balance.account, balance.as_of.isoformat(), balance.amount_cents),
        )


def save_pending_state(conn: sqlite3.Connection, state_hash: str, created_at: datetime) -> None:
    """Remember the hash of the issued state, replacing any earlier one."""
    with conn:
        conn.execute(
            """
            INSERT INTO bank_authorization (id, state_hash, created_at) VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state_hash = excluded.state_hash, created_at = excluded.created_at
            """,
            (state_hash, _format(created_at)),
        )


def take_pending_state(conn: sqlite3.Connection) -> tuple[str, datetime] | None:
    """The pending state hash and its creation time; the row is always deleted (single use)."""
    with conn:
        row = conn.execute(
            "SELECT state_hash, created_at FROM bank_authorization WHERE id = 1"
        ).fetchone()
        conn.execute("DELETE FROM bank_authorization WHERE id = 1")
    if row is None:
        return None
    return row[0], _parse(row[1])


def _format(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text)
