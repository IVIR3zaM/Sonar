"""Tests for migration 0017: garden link, garden fee and zeroed intervals (SPEC §13)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.utilities.model import FieldError, Meter
from sonar.utilities.store import add_meter


def _migrated_before_0017(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name < "0017":
            shutil.copy(path, migrations)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations)
    return conn, migrations


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO utility_meters (id, name, kind) VALUES (4, 'Water', 'water')")
    conn.execute(
        "INSERT INTO utility_readings (id, meter_id, reading_date, value_milli) "
        "VALUES (9, 4, '2026-01-01', 1000000)"
    )
    conn.execute(
        "INSERT INTO utility_exchanges (id, meter_id, exchange_date, old_final_milli, "
        "new_start_milli) VALUES (6, 4, '2026-03-01', 1200000, 500)"
    )
    conn.execute(
        "INSERT INTO utility_periods (id, meter_id, start_date, settlement_date, "
        "advance_cents, expected_usage) VALUES (3, 4, '2026-01-01', '2026-12-31', 9000, 15)"
    )
    conn.execute(
        "INSERT INTO utility_advance_dates (id, period_id, due_date) VALUES (2, 3, '2026-02-05')"
    )
    conn.commit()


def test_existing_rows_survive_with_null_garden_columns(tmp_path):
    conn, migrations = _migrated_before_0017(tmp_path)
    _seed(conn)
    shutil.copy(MIGRATIONS_DIR / "0017_garden_meters.sql", migrations)

    apply_migrations(conn, migrations)

    assert conn.execute("SELECT id, name, kind, main_meter_id FROM utility_meters").fetchall() == [
        (4, "Water", "water", None)
    ]
    assert conn.execute("SELECT * FROM utility_readings").fetchall() == [
        (9, 4, "2026-01-01", 1_000_000)
    ]
    assert conn.execute("SELECT * FROM utility_exchanges").fetchall() == [
        (6, 4, "2026-03-01", 1_200_000, 500)
    ]
    assert conn.execute(
        "SELECT id, meter_id, start_date, advance_cents, garden_fee_cents FROM utility_periods"
    ).fetchall() == [(3, 4, "2026-01-01", 9000, None)]
    assert conn.execute("SELECT id, period_id, due_date FROM utility_advance_dates").fetchall() == [
        (2, 3, "2026-02-05")
    ]
    assert conn.execute("SELECT COUNT(*) FROM utility_garden_zeroed").fetchone() == (0,)


def test_a_garden_link_to_a_gas_meter_is_refused():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    gas = add_meter(conn, Meter("Gas", "gas"))

    with pytest.raises(FieldError) as error:
        add_meter(conn, Meter("Garden", "water", gas))

    assert error.value.field == "main_meter_id"
    assert conn.execute("SELECT COUNT(*) FROM utility_meters").fetchone() == (1,)


def test_a_zeroed_interval_is_unique_per_meter():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    conn.execute("INSERT INTO utility_meters (id, name, kind) VALUES (1, 'Water', 'water')")
    insert = "INSERT INTO utility_garden_zeroed (meter_id, start_date, end_date) VALUES (1, ?, ?)"
    conn.execute(insert, ("2026-01-01", "2026-02-01"))

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("2026-01-01", "2026-02-01"))
