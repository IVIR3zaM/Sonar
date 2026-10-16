"""Tests for migration 0014: the energy tables (SPEC §13 Energy)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations

ENERGY_TABLES = {"energy_meters", "energy_readings", "energy_exchanges", "energy_periods"}
EXISTING = ("transactions", "categories", "debts")


def _migrated_before(tmp_path: Path, cutoff: str) -> tuple[sqlite3.Connection, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name < cutoff:
            shutil.copy(path, migrations)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations)
    return conn, migrations


def _migrated_before_0014(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    return _migrated_before(tmp_path, "0014")


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _dump(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in EXISTING}


def test_existing_data_is_unchanged_and_the_four_tables_appear(tmp_path):
    conn, migrations = _migrated_before_0014(tmp_path)
    conn.execute("INSERT INTO categories (name, type) VALUES ('Mine', 'fixed')")
    conn.execute(
        """
        INSERT INTO debts (
            id, kind, name, rate_cents, match_field, match_value,
            balance_cents, balance_as_of, interest_bp
        ) VALUES (7, 'loan', 'Car', 5000, 'mandate', 'M-1', 90000, '2026-06-30', 350)
        """
    )
    conn.commit()
    transactions = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
    before = _dump(conn)
    assert not ENERGY_TABLES & _tables(conn)
    shutil.copy(MIGRATIONS_DIR / "0014_energy.sql", migrations)

    apply_migrations(conn, migrations)

    assert _dump(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone() == transactions
    assert ENERGY_TABLES <= _tables(conn)


READING = "INSERT INTO energy_readings (meter_id, reading_date, value_milli) VALUES (1, ?, ?)"
EXCHANGE = """
    INSERT INTO energy_exchanges (meter_id, exchange_date, old_final_milli, new_start_milli)
    VALUES (1, ?, ?, 0)
"""


def test_constraints_reject_bad_rows(tmp_path):
    # Later migrations rename these tables and allow water meters.
    conn, _ = _migrated_before(tmp_path, "0015")
    conn.execute("INSERT INTO energy_meters (id, name, kind) VALUES (1, 'Gas', 'gas')")
    conn.execute(READING, ("2026-01-01", 5))
    conn.execute(EXCHANGE, ("2026-01-01", 5))

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO energy_meters (name, kind) VALUES ('Gas', 'gas')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO energy_meters (name, kind) VALUES ('Water', 'water')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(READING, ("2026-01-01", 6))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(EXCHANGE, ("2026-01-01", 6))
