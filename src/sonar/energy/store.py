"""DB shell for energy meters (SPEC §13 Energy): storage only.

`model.py` and `usage.py` hold the pure rules. Every write here is applied inside
a transaction, then the meter's resulting rows are re-checked with them; a
FieldError rolls the write back, so a rejected input changes nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.energy.model import (
    BillingPeriod,
    Exchange,
    FieldError,
    Meter,
    Reading,
    check_periods,
)
from sonar.energy.usage import check_series

_PERIOD_SELECT = """
    SELECT p.id, p.start_date, p.settlement_date, p.base_fee_cents, p.unit_price_micro,
           p.state_factor_e4, p.calorific_value_e4, p.advance_cents, p.expected_kwh, c.name,
           p.settled_cents
    FROM energy_periods p LEFT JOIN categories c ON c.id = p.category_id
"""


class EnergyNotFound(LookupError):
    """An id (meter, reading, exchange or period) has no matching row."""


class MeterNotEmpty(Exception):
    """A meter with readings, exchanges or periods cannot be deleted."""


@dataclass(frozen=True)
class Stored[T]:
    id: int
    item: T


# Meters


def list_meters(conn: sqlite3.Connection) -> list[Stored[Meter]]:
    rows = conn.execute("SELECT id, name, kind FROM energy_meters ORDER BY name").fetchall()
    return [Stored(id, Meter(name, kind)) for id, name, kind in rows]


def add_meter(conn: sqlite3.Connection, meter: Meter) -> int:
    with conn:
        try:
            cursor = conn.execute(
                "INSERT INTO energy_meters (name, kind) VALUES (?, ?)", (meter.name, meter.kind)
            )
        except sqlite3.IntegrityError:
            raise _duplicate_name(meter.name) from None
    return cursor.lastrowid


def rename_meter(conn: sqlite3.Connection, meter_id: int, name: str) -> None:
    with conn:
        kind = _meter_kind(conn, meter_id)
        Meter(name, kind)  # validates the name
        try:
            conn.execute("UPDATE energy_meters SET name = ? WHERE id = ?", (name, meter_id))
        except sqlite3.IntegrityError:
            raise _duplicate_name(name) from None


def delete_meter(conn: sqlite3.Connection, meter_id: int) -> None:
    with conn:
        _meter_kind(conn, meter_id)
        for table in ("energy_readings", "energy_exchanges", "energy_periods"):
            if conn.execute(f"SELECT 1 FROM {table} WHERE meter_id = ?", (meter_id,)).fetchone():
                raise MeterNotEmpty(meter_id)
        conn.execute("DELETE FROM energy_meters WHERE id = ?", (meter_id,))


# Readings


def list_readings(conn: sqlite3.Connection, meter_id: int) -> list[Stored[Reading]]:
    _meter_kind(conn, meter_id)
    return _readings(conn, meter_id)


def add_reading(conn: sqlite3.Connection, meter_id: int, reading: Reading) -> int:
    with conn:
        _meter_kind(conn, meter_id)
        cursor = _write_dated(
            conn,
            "INSERT INTO energy_readings (meter_id, reading_date, value_milli) VALUES (?, ?, ?)",
            (meter_id, reading.reading_date.isoformat(), reading.value_milli),
            reading.reading_date,
        )
        _check_series(conn, meter_id)
    return cursor.lastrowid


def update_reading(conn: sqlite3.Connection, reading_id: int, reading: Reading) -> None:
    with conn:
        meter_id = _owner(conn, "energy_readings", reading_id)
        _write_dated(
            conn,
            "UPDATE energy_readings SET reading_date = ?, value_milli = ? WHERE id = ?",
            (reading.reading_date.isoformat(), reading.value_milli, reading_id),
            reading.reading_date,
        )
        _check_series(conn, meter_id)


def delete_reading(conn: sqlite3.Connection, reading_id: int) -> None:
    with conn:
        meter_id = _owner(conn, "energy_readings", reading_id)
        conn.execute("DELETE FROM energy_readings WHERE id = ?", (reading_id,))
        _check_series(conn, meter_id)


# Exchanges


def list_exchanges(conn: sqlite3.Connection, meter_id: int) -> list[Stored[Exchange]]:
    _meter_kind(conn, meter_id)
    return _exchanges(conn, meter_id)


def add_exchange(conn: sqlite3.Connection, meter_id: int, exchange: Exchange) -> int:
    with conn:
        _meter_kind(conn, meter_id)
        cursor = _write_dated(
            conn,
            "INSERT INTO energy_exchanges "
            "(meter_id, exchange_date, old_final_milli, new_start_milli) VALUES (?, ?, ?, ?)",
            (
                meter_id,
                exchange.exchange_date.isoformat(),
                exchange.old_final_milli,
                exchange.new_start_milli,
            ),
            exchange.exchange_date,
        )
        _check_series(conn, meter_id)
    return cursor.lastrowid


def update_exchange(conn: sqlite3.Connection, exchange_id: int, exchange: Exchange) -> None:
    with conn:
        meter_id = _owner(conn, "energy_exchanges", exchange_id)
        _write_dated(
            conn,
            "UPDATE energy_exchanges SET exchange_date = ?, old_final_milli = ?, "
            "new_start_milli = ? WHERE id = ?",
            (
                exchange.exchange_date.isoformat(),
                exchange.old_final_milli,
                exchange.new_start_milli,
                exchange_id,
            ),
            exchange.exchange_date,
        )
        _check_series(conn, meter_id)


def delete_exchange(conn: sqlite3.Connection, exchange_id: int) -> None:
    with conn:
        meter_id = _owner(conn, "energy_exchanges", exchange_id)
        conn.execute("DELETE FROM energy_exchanges WHERE id = ?", (exchange_id,))
        _check_series(conn, meter_id)


# Billing periods


def list_periods(conn: sqlite3.Connection, meter_id: int) -> list[Stored[BillingPeriod]]:
    _meter_kind(conn, meter_id)
    return _periods(conn, meter_id)


def add_period(conn: sqlite3.Connection, meter_id: int, period: BillingPeriod) -> int:
    with conn:
        _meter_kind(conn, meter_id)
        category_id = _category_id(conn, period.category)
        cursor = conn.execute(
            """
            INSERT INTO energy_periods (
                meter_id, start_date, settlement_date, base_fee_cents, unit_price_micro,
                state_factor_e4, calorific_value_e4, advance_cents, expected_kwh, category_id,
                settled_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (meter_id, *_period_values(period), category_id, period.settled_cents),
        )
        _check_periods(conn, meter_id)
    return cursor.lastrowid


def period_settled_cents(conn: sqlite3.Connection, period_id: int) -> int | None:
    row = conn.execute(
        "SELECT settled_cents FROM energy_periods WHERE id = ?", (period_id,)
    ).fetchone()
    if row is None:
        raise EnergyNotFound(period_id)
    return row[0]


def update_period(conn: sqlite3.Connection, period_id: int, period: BillingPeriod) -> None:
    with conn:
        meter_id = _owner(conn, "energy_periods", period_id)
        category_id = _category_id(conn, period.category)
        conn.execute(
            """
            UPDATE energy_periods SET
                start_date = ?, settlement_date = ?, base_fee_cents = ?, unit_price_micro = ?,
                state_factor_e4 = ?, calorific_value_e4 = ?, advance_cents = ?,
                expected_kwh = ?, category_id = ?, settled_cents = ?
            WHERE id = ?
            """,
            (*_period_values(period), category_id, period.settled_cents, period_id),
        )
        _check_periods(conn, meter_id)


def delete_period(conn: sqlite3.Connection, period_id: int) -> None:
    with conn:
        _owner(conn, "energy_periods", period_id)
        conn.execute("DELETE FROM energy_periods WHERE id = ?", (period_id,))


# Helpers


def _duplicate_name(name: str) -> FieldError:
    return FieldError("name", f"a meter named {name!r} already exists")


def _meter_kind(conn: sqlite3.Connection, meter_id: int) -> str:
    row = conn.execute("SELECT kind FROM energy_meters WHERE id = ?", (meter_id,)).fetchone()
    if row is None:
        raise EnergyNotFound(meter_id)
    return row[0]


def _owner(conn: sqlite3.Connection, table: str, row_id: int) -> int:
    """The meter id a reading, exchange or period belongs to."""
    row = conn.execute(f"SELECT meter_id FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise EnergyNotFound(row_id)
    return row[0]


def _write_dated(conn: sqlite3.Connection, sql: str, params: tuple, day: date) -> sqlite3.Cursor:
    # The unique (meter, date) index reports a repeated date of the same table.
    try:
        return conn.execute(sql, params)
    except sqlite3.IntegrityError:
        raise FieldError("date", f"only one reading or exchange on {day.isoformat()}") from None


def _category_id(conn: sqlite3.Connection, name: str | None) -> int | None:
    if name is None:
        return None
    row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise FieldError("category", f"unknown category {name!r}")
    return row[0]


def _period_values(period: BillingPeriod) -> tuple:
    return (
        period.start_date.isoformat(),
        period.settlement_date.isoformat(),
        period.base_fee_cents,
        period.unit_price_micro,
        period.state_factor_e4,
        period.calorific_value_e4,
        period.advance_cents,
        period.expected_kwh,
    )


def _check_series(conn: sqlite3.Connection, meter_id: int) -> None:
    check_series(
        [stored.item for stored in _readings(conn, meter_id)],
        [stored.item for stored in _exchanges(conn, meter_id)],
    )


def _check_periods(conn: sqlite3.Connection, meter_id: int) -> None:
    kind = _meter_kind(conn, meter_id)
    check_periods([stored.item for stored in _periods(conn, meter_id)], kind)


def _readings(conn: sqlite3.Connection, meter_id: int) -> list[Stored[Reading]]:
    rows = conn.execute(
        "SELECT id, reading_date, value_milli FROM energy_readings "
        "WHERE meter_id = ? ORDER BY reading_date",
        (meter_id,),
    ).fetchall()
    return [Stored(id, Reading(date.fromisoformat(day), value)) for id, day, value in rows]


def _exchanges(conn: sqlite3.Connection, meter_id: int) -> list[Stored[Exchange]]:
    rows = conn.execute(
        "SELECT id, exchange_date, old_final_milli, new_start_milli FROM energy_exchanges "
        "WHERE meter_id = ? ORDER BY exchange_date",
        (meter_id,),
    ).fetchall()
    return [
        Stored(id, Exchange(date.fromisoformat(day), old_final, new_start))
        for id, day, old_final, new_start in rows
    ]


def _periods(conn: sqlite3.Connection, meter_id: int) -> list[Stored[BillingPeriod]]:
    rows = conn.execute(
        f"{_PERIOD_SELECT} WHERE p.meter_id = ? ORDER BY p.start_date", (meter_id,)
    ).fetchall()
    return [
        Stored(
            id,
            BillingPeriod(
                start_date=date.fromisoformat(start),
                settlement_date=date.fromisoformat(settlement),
                base_fee_cents=base_fee,
                unit_price_micro=unit_price,
                state_factor_e4=state_factor,
                calorific_value_e4=calorific,
                advance_cents=advance,
                expected_kwh=expected,
                category=category,
                settled_cents=settled,
            ),
        )
        for (
            id,
            start,
            settlement,
            base_fee,
            unit_price,
            state_factor,
            calorific,
            advance,
            expected,
            category,
            settled,
        ) in rows
    ]
