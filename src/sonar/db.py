"""Database connection and migration runner.

Schema changes are plain SQL files named `NNNN_description.sql` in a
migrations directory, applied in numeric order and tracked in
`schema_migrations` so each file runs at most once, even across restarts.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection, creating the database's parent directory."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def apply_migrations(conn: sqlite3.Connection, migrations_dir: str | Path) -> list[str]:
    """Apply unapplied `NNNN_*.sql` files in `migrations_dir`, in numeric order.

    Returns the names of the files applied. A missing directory means there
    are no migrations to apply.
    """
    # `Cursor.executescript()` implicitly commits any pending transaction
    # before it runs, so on a connection in legacy autocommit mode a DDL
    # statement inside the script would already be persisted before a later
    # statement in the same file fails. Autocommit=False keeps the whole
    # script in one transaction that we can roll back on error.
    conn.autocommit = False

    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)"
    )
    conn.commit()

    migrations_dir = Path(migrations_dir)
    if not migrations_dir.is_dir():
        return []

    already_applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}

    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        name = path.name
        if name in already_applied:
            continue

        try:
            conn.executescript(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (name, datetime.now(UTC).isoformat()),
            )
        except sqlite3.Error:
            conn.rollback()
            raise
        else:
            conn.commit()
            applied.append(name)

    return applied
