"""Shared test helper: seed a DB with a fake taxonomy.

Tests never point `create_app` at a TOML file (N05): they migrate a tmp DB
and store a fake taxonomy directly, the same path the `import-categories` CLI
and the Categories page use. Real bank data or category names never belong
here; `seed` takes fake `categories.toml`-syntax text only.
"""

from __future__ import annotations

from pathlib import Path

from sonar.categorization.rules import parse_taxonomy
from sonar.categorization.store import replace_taxonomy
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect


def seed(db_path: Path, toml_text: str = "") -> None:
    """Migrate `db_path` and replace its taxonomy with `toml_text` (fake categories.toml syntax)."""
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        replace_taxonomy(conn, parse_taxonomy(toml_text))
    finally:
        conn.close()
