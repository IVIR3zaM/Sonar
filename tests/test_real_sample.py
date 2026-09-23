"""Opt-in tests for real sample imports (SPEC §4).

Tests run only if samples/ contains .csv files and never assert on row content.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sonar.db import apply_migrations
from sonar.importing import import_file

REPO_ROOT = Path(__file__).parent.parent
MIGRATIONS_DIR = REPO_ROOT / "src" / "sonar" / "migrations"
SAMPLES_DIR = REPO_ROOT / "samples"


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _get_sample_files() -> list[Path]:
    """Glob all .csv files in samples/ directory."""
    if not SAMPLES_DIR.is_dir():
        return []
    return sorted(SAMPLES_DIR.glob("*.csv"))


def _count_transactions(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


def _count_balances(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0]


@pytest.mark.parametrize("sample_path", _get_sample_files(), ids=lambda p: p.name)
def test_real_sample_import_is_idempotent(conn: sqlite3.Connection, sample_path: Path) -> None:
    """Importing a real sample succeeds, storing transactions and balance; re-import adds 0 rows."""
    content = sample_path.read_bytes()

    # First import
    result = import_file(conn, content, sample_path.name)
    first_tx_count = _count_transactions(conn)
    first_balance_count = _count_balances(conn)

    assert result.added > 0, f"First import added {result.added} transactions"
    assert first_tx_count > 0, f"Stored {first_tx_count} transactions after first import"
    assert first_balance_count > 0, (
        f"Stored {first_balance_count} balance entries after first import"
    )

    # Re-import the same file
    result2 = import_file(conn, content, sample_path.name)
    second_tx_count = _count_transactions(conn)
    second_balance_count = _count_balances(conn)

    assert result2.added == 0, f"Re-import added {result2.added} transactions (expected 0)"
    assert second_tx_count == first_tx_count, (
        f"Transaction count changed from {first_tx_count} to {second_tx_count}"
    )
    assert second_balance_count == first_balance_count, (
        f"Balance count changed from {first_balance_count} to {second_balance_count}"
    )
