"""Bank connection storage (SPEC §13 Bank sync): the connection and the pending authorization."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from sonar.banking.consent import BankConnection, NewConnection


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
