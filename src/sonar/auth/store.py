"""DB shell for the sign-in allow-list (SPEC §13 Access list): `allowed_emails` (0007).

Every function normalizes its input, so callers may pass an email as typed.
`is_allowed` is what the web layer calls on every request.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from sonar.auth.emails import normalize_email


def allow_email(conn: sqlite3.Connection, email: str, now: datetime) -> None:
    """Add `email` to the list; adding one already listed changes nothing."""
    normalized = normalize_email(email)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO allowed_emails (email, added_at) VALUES (?, ?)",
            (normalized, now.isoformat()),
        )


def revoke_email(conn: sqlite3.Connection, email: str) -> bool:
    """Remove `email` from the list; False when it was not on it."""
    normalized = normalize_email(email)
    with conn:
        cursor = conn.execute("DELETE FROM allowed_emails WHERE email = ?", (normalized,))
    return cursor.rowcount > 0


def list_emails(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT email FROM allowed_emails ORDER BY email")]


def sync_emails(conn: sqlite3.Connection, emails: list[str], now: datetime) -> None:
    """Make the list exactly `emails`; the table is untouched if any is invalid or none given."""
    if not emails:
        raise ValueError("Give at least one email: syncing an empty list would lock everyone out.")
    wanted = {normalize_email(email) for email in emails}
    with conn:
        # Listed emails keep their original added_at.
        conn.execute(
            f"DELETE FROM allowed_emails WHERE email NOT IN ({','.join('?' * len(wanted))})",
            sorted(wanted),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO allowed_emails (email, added_at) VALUES (?, ?)",
            [(email, now.isoformat()) for email in sorted(wanted)],
        )


def is_allowed(conn: sqlite3.Connection, email: str) -> bool:
    try:
        normalized = normalize_email(email)
    except ValueError:
        return False
    row = conn.execute("SELECT 1 FROM allowed_emails WHERE email = ?", (normalized,)).fetchone()
    return row is not None
