"""Tests for migration 0016: Energy tables become Utilities tables and gain water (SPEC §13)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations

NEW_PERIOD_COLUMNS = (
    "advance_mode, settlement_debit_days, drinking_price_micro, drinking_base_fee_cents, "
    "drinking_vat_percent, wastewater_price_micro, wastewater_base_fee_cents, "
    "wastewater_vat_percent"
)


def _migrated_before_0016(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0016":
            shutil.copy(path, migrations)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations)
    return conn, migrations


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO energy_meters (id, name, kind) VALUES (4, 'Gas', 'gas')")
    conn.execute(
        "INSERT INTO energy_readings (id, meter_id, reading_date, value_milli) "
        "VALUES (9, 4, '2026-01-01', 1000000)"
    )
    conn.execute(
        "INSERT INTO energy_exchanges (id, meter_id, exchange_date, old_final_milli, "
        "new_start_milli) VALUES (6, 4, '2026-03-01', 1200000, 500)"
    )
    conn.execute(
        """
        INSERT INTO energy_periods (
            id, meter_id, start_date, settlement_date, base_fee_cents, unit_price_micro,
            state_factor_e4, calorific_value_e4, advance_cents, expected_kwh, category_id,
            settled_cents
        ) VALUES
            (3, 4, '2025-01-01', '2025-12-31', 1100, 70000, 9400, 109000, 8000, 14000, 2, -3169),
            (5, 4, '2026-01-01', '2026-12-31', 1200, 80000, 9500, 110000, 9000, 15000, NULL, NULL)
        """
    )
    conn.commit()


def test_every_row_keeps_its_id_and_values_with_neutral_new_columns(tmp_path):
    conn, migrations = _migrated_before_0016(tmp_path)
    _seed(conn)
    shutil.copy(MIGRATIONS_DIR / "0016_utilities.sql", migrations)

    apply_migrations(conn, migrations)

    assert conn.execute("SELECT id, name, kind FROM utility_meters").fetchall() == [
        (4, "Gas", "gas")
    ]
    assert conn.execute("SELECT * FROM utility_readings").fetchall() == [
        (9, 4, "2026-01-01", 1_000_000)
    ]
    assert conn.execute("SELECT * FROM utility_exchanges").fetchall() == [
        (6, 4, "2026-03-01", 1_200_000, 500)
    ]
    assert conn.execute(
        """
        SELECT id, meter_id, start_date, settlement_date, base_fee_cents, unit_price_micro,
               state_factor_e4, calorific_value_e4, advance_cents, expected_usage, category_id,
               settled_cents
        FROM utility_periods ORDER BY id
        """
    ).fetchall() == [
        (3, 4, "2025-01-01", "2025-12-31", 1100, 70000, 9400, 109000, 8000, 14000, 2, -3169),
        (5, 4, "2026-01-01", "2026-12-31", 1200, 80000, 9500, 110000, 9000, 15000, None, None),
    ]
    assert (
        conn.execute(f"SELECT {NEW_PERIOD_COLUMNS} FROM utility_periods ORDER BY id").fetchall()
        == [("flexible", 0, None, None, None, None, None, None)] * 2
    )
    assert conn.execute("SELECT COUNT(*) FROM utility_advance_dates").fetchone() == (0,)


def test_no_energy_table_is_left(tmp_path):
    conn, migrations = _migrated_before_0016(tmp_path)
    _seed(conn)
    shutil.copy(MIGRATIONS_DIR / "0016_utilities.sql", migrations)

    apply_migrations(conn, migrations)

    tables = _tables(conn)
    assert not {t for t in tables if t.startswith("energy_")}
    assert {
        "utility_meters",
        "utility_readings",
        "utility_exchanges",
        "utility_periods",
        "utility_advance_dates",
    } <= tables


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_water_meters_are_allowed_and_other_kinds_are_not(conn):
    conn.execute("INSERT INTO utility_meters (name, kind) VALUES ('Water', 'water')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO utility_meters (name, kind) VALUES ('Fuel', 'oil')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO utility_meters (name, kind) VALUES ('Water', 'gas')")


def test_constraints_reject_bad_rows(conn):
    conn.execute("INSERT INTO utility_meters (id, name, kind) VALUES (1, 'Water', 'water')")
    conn.execute(
        "INSERT INTO utility_periods (id, meter_id, start_date, settlement_date, advance_cents, "
        "expected_usage) VALUES (1, 1, '2026-01-01', '2026-12-31', 0, 0)"
    )
    conn.execute("INSERT INTO utility_advance_dates (period_id, due_date) VALUES (1, '2026-02-01')")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO utility_periods (meter_id, start_date, settlement_date, advance_cents, "
            "expected_usage, advance_mode) VALUES (1, '2027-01-01', '2027-12-31', 0, 0, 'weekly')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO utility_advance_dates (period_id, due_date) VALUES (1, '2026-02-01')"
        )
