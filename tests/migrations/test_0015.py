"""Tests for migration 0015: the settled amount on billing periods (SPEC §13)."""

import shutil
import sqlite3
from pathlib import Path

from sonar.db import MIGRATIONS_DIR, apply_migrations


def _migrated_before_0015(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0015":
            shutil.copy(path, migrations)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations)
    return conn, migrations


def test_a_period_stored_before_0015_survives_with_no_settled_amount(tmp_path):
    conn, migrations = _migrated_before_0015(tmp_path)
    conn.execute("INSERT INTO energy_meters (id, name, kind) VALUES (1, 'Gas', 'gas')")
    conn.execute(
        """
        INSERT INTO energy_periods (
            id, meter_id, start_date, settlement_date, base_fee_cents, unit_price_micro,
            state_factor_e4, calorific_value_e4, advance_cents, expected_kwh
        ) VALUES (3, 1, '2026-01-01', '2026-12-31', 1200, 80000, 9500, 110000, 9000, 15000)
        """
    )
    conn.commit()
    before = conn.execute("SELECT * FROM energy_periods").fetchall()
    shutil.copy(MIGRATIONS_DIR / "0015_energy_settled.sql", migrations)

    apply_migrations(conn, migrations)

    [row] = conn.execute("SELECT * FROM energy_periods").fetchall()
    assert row[: len(before[0])] == before[0]
    assert conn.execute("SELECT settled_cents FROM energy_periods WHERE id = 3").fetchone() == (
        None,
    )
