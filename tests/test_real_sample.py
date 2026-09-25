"""Opt-in tests for real sample imports (SPEC §4, §6).

Tests run only if samples/ contains .csv files and never assert on row content.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from sonar.categorize import load_taxonomy
from sonar.categorizing import reapply_rules
from sonar.dashboard import load_dashboard
from sonar.db import apply_migrations
from sonar.importing import import_file
from sonar.recurring import sync_detected
from sonar.settings_store import DEFAULT_OVERDRAFT_LIMIT_CENTS, save_settings
from sonar.taxonomy_store import load_stored_taxonomy, replace_taxonomy

REPO_ROOT = Path(__file__).parent.parent
MIGRATIONS_DIR = REPO_ROOT / "src" / "sonar" / "migrations"
SAMPLES_DIR = REPO_ROOT / "samples"
REAL_CATEGORIES_TOML = REPO_ROOT / "data" / "categories.toml"


@pytest.fixture
def conn() -> sqlite3.Connection:
    # The DB's own stored taxonomy (N05), seeded once here from the owner's
    # local data/categories.toml (N11; untracked, imported with
    # `uv run sonar import-categories`), the same path the CLI takes.
    if not REAL_CATEGORIES_TOML.exists():
        pytest.skip(f"{REAL_CATEGORIES_TOML} not found; run import-categories first")
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    replace_taxonomy(conn, load_taxonomy(REAL_CATEGORIES_TOML))
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


def _count_uncategorized(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM transactions WHERE category IS NULL").fetchone()[0]


@pytest.mark.parametrize("sample_path", _get_sample_files(), ids=lambda p: p.name)
def test_real_sample_import_is_idempotent(conn: sqlite3.Connection, sample_path: Path) -> None:
    """Importing a real sample succeeds, storing transactions and balance; re-import adds 0 rows."""
    content = sample_path.read_bytes()

    result = import_file(conn, content, sample_path.name)
    first_tx_count = _count_transactions(conn)
    first_balance_count = _count_balances(conn)

    assert result.added > 0, f"First import added {result.added} transactions"
    assert first_tx_count > 0, f"Stored {first_tx_count} transactions after first import"
    assert first_balance_count > 0, (
        f"Stored {first_balance_count} balance entries after first import"
    )

    # Re-importing the same export must add nothing (SPEC §4 idempotency).
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


@pytest.mark.parametrize("sample_path", _get_sample_files(), ids=lambda p: p.name)
def test_real_sample_categorization(conn: sqlite3.Connection, sample_path: Path) -> None:
    """Import with rules; assert some rows are categorized; reapply is idempotent."""
    content = sample_path.read_bytes()
    taxonomy = load_stored_taxonomy(conn)

    result = import_file(conn, content, sample_path.name, rules=taxonomy.rules)

    uncategorized = _count_uncategorized(conn)
    assert uncategorized < result.added, (
        f"Uncategorized {uncategorized} should be less than added {result.added}"
    )

    changed = reapply_rules(conn, taxonomy.rules)
    assert changed == 0, f"Reapply changed {changed} rows (expected 0)"


@pytest.mark.parametrize("sample_path", _get_sample_files(), ids=lambda p: p.name)
def test_real_sample_recurring_detection(conn: sqlite3.Connection, sample_path: Path) -> None:
    """sync_detected detects >= 1 payment after import; second sync is idempotent."""
    content = sample_path.read_bytes()
    taxonomy = load_stored_taxonomy(conn)

    import_file(conn, content, sample_path.name, rules=taxonomy.rules)

    changed = sync_detected(conn, taxonomy.categories, date(2026, 9, 23))
    assert changed >= 1, f"First sync detected {changed} payments (expected >= 1)"

    # A second sync must be a no-op, or every page load would rewrite the schedule.
    changed2 = sync_detected(conn, taxonomy.categories, date(2026, 9, 23))
    assert changed2 == 0, f"Second sync changed {changed2} rows (expected 0)"


@pytest.mark.parametrize("sample_path", _get_sample_files(), ids=lambda p: p.name)
def test_real_sample_dashboard_load(conn: sqlite3.Connection, sample_path: Path) -> None:
    """Load dashboard after importing sample with taxonomy and saved settings."""
    content = sample_path.read_bytes()
    taxonomy = load_stored_taxonomy(conn)

    import_file(conn, content, sample_path.name, rules=taxonomy.rules)

    save_settings(conn, 26, DEFAULT_OVERDRAFT_LIMIT_CENTS)

    dashboard = load_dashboard(conn, taxonomy.categories, date(2026, 9, 23))

    assert dashboard.balance is not None, "Dashboard balance should not be None"

    assert dashboard.payday == date(2026, 9, 25), (
        f"Dashboard payday should be 2026-09-25, got {dashboard.payday}"
    )

    assert len(dashboard.fixed_costs.months) == 12, (
        f"Fixed costs should have 12 months, got {len(dashboard.fixed_costs.months)}"
    )

    assert dashboard.light in {"green", "yellow", "red"}, (
        f"Dashboard light should be 'green', 'yellow', or 'red', got {dashboard.light}"
    )
