"""DB shell for utility meters (SPEC §13 Utilities): storage only.

`model.py` and `usage.py` hold the pure rules. Every write here is applied inside
a transaction, then the meter's resulting rows are re-checked with them; a
FieldError rolls the write back, so a rejected input changes nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.utilities.model import (
    BillingPeriod,
    Charge,
    Exchange,
    FieldError,
    Meter,
    Reading,
    check_period,
    check_periods,
)
from sonar.utilities.usage import check_series

_PERIOD_COLUMN_NAMES = (
    "start_date",
    "settlement_date",
    "base_fee_cents",
    "unit_price_micro",
    "state_factor_e4",
    "calorific_value_e4",
    "advance_cents",
    "expected_usage",
    "settled_cents",
    "advance_mode",
    "settlement_debit_days",
    "drinking_price_micro",
    "drinking_base_fee_cents",
    "drinking_vat_percent",
    "wastewater_price_micro",
    "wastewater_base_fee_cents",
    "wastewater_vat_percent",
    "garden_fee_cents",
)
_PERIOD_COLUMNS = ", ".join(_PERIOD_COLUMN_NAMES)
_PERIOD_PLACEHOLDERS = ", ".join("?" for _ in _PERIOD_COLUMN_NAMES)

_PERIOD_SELECT = """
    SELECT p.id, p.start_date, p.settlement_date, p.base_fee_cents, p.unit_price_micro,
           p.state_factor_e4, p.calorific_value_e4, p.advance_cents, p.expected_usage, c.name,
           p.settled_cents, p.advance_mode, p.settlement_debit_days,
           p.drinking_price_micro, p.drinking_base_fee_cents, p.drinking_vat_percent,
           p.wastewater_price_micro, p.wastewater_base_fee_cents, p.wastewater_vat_percent,
           p.garden_fee_cents
    FROM utility_periods p LEFT JOIN categories c ON c.id = p.category_id
"""


class UtilityNotFound(LookupError):
    """An id (meter, reading, exchange or period) has no matching row."""


class MeterNotEmpty(Exception):
    """A meter with readings, exchanges, periods or garden meters cannot be deleted."""


@dataclass(frozen=True)
class Stored[T]:
    id: int
    item: T


# Meters


def list_meters(conn: sqlite3.Connection) -> list[Stored[Meter]]:
    rows = conn.execute(
        "SELECT id, name, kind, main_meter_id FROM utility_meters ORDER BY name"
    ).fetchall()
    return [Stored(id, Meter(name, kind, main)) for id, name, kind, main in rows]


def add_meter(conn: sqlite3.Connection, meter: Meter) -> int:
    with conn:
        _check_main_meter(conn, meter)
        try:
            cursor = conn.execute(
                "INSERT INTO utility_meters (name, kind, main_meter_id) VALUES (?, ?, ?)",
                (meter.name, meter.kind, meter.main_meter_id),
            )
        except sqlite3.IntegrityError:
            raise _duplicate_name(meter.name) from None
    return cursor.lastrowid


def rename_meter(conn: sqlite3.Connection, meter_id: int, name: str) -> None:
    with conn:
        kind = _meter_kind(conn, meter_id)
        Meter(name, kind)  # validates the name
        try:
            conn.execute("UPDATE utility_meters SET name = ? WHERE id = ?", (name, meter_id))
        except sqlite3.IntegrityError:
            raise _duplicate_name(name) from None


def delete_meter(conn: sqlite3.Connection, meter_id: int) -> None:
    with conn:
        _meter_kind(conn, meter_id)
        for table in ("utility_readings", "utility_exchanges", "utility_periods"):
            if conn.execute(f"SELECT 1 FROM {table} WHERE meter_id = ?", (meter_id,)).fetchone():
                raise MeterNotEmpty(meter_id)
        if conn.execute(
            "SELECT 1 FROM utility_meters WHERE main_meter_id = ?", (meter_id,)
        ).fetchone():
            raise MeterNotEmpty(meter_id)
        conn.execute("DELETE FROM utility_garden_zeroed WHERE meter_id = ?", (meter_id,))
        conn.execute("DELETE FROM utility_meters WHERE id = ?", (meter_id,))


# Readings


def list_readings(conn: sqlite3.Connection, meter_id: int) -> list[Stored[Reading]]:
    _meter_kind(conn, meter_id)
    return _readings(conn, meter_id)


def add_reading(conn: sqlite3.Connection, meter_id: int, reading: Reading) -> int:
    with conn:
        _meter_kind(conn, meter_id)
        cursor = _write_dated(
            conn,
            "INSERT INTO utility_readings (meter_id, reading_date, value_milli) VALUES (?, ?, ?)",
            (meter_id, reading.reading_date.isoformat(), reading.value_milli),
            reading.reading_date,
        )
        _check_series(conn, meter_id)
    return cursor.lastrowid


def update_reading(conn: sqlite3.Connection, reading_id: int, reading: Reading) -> None:
    with conn:
        meter_id = _owner(conn, "utility_readings", reading_id)
        _write_dated(
            conn,
            "UPDATE utility_readings SET reading_date = ?, value_milli = ? WHERE id = ?",
            (reading.reading_date.isoformat(), reading.value_milli, reading_id),
            reading.reading_date,
        )
        _check_series(conn, meter_id)


def delete_reading(conn: sqlite3.Connection, reading_id: int) -> None:
    with conn:
        meter_id = _owner(conn, "utility_readings", reading_id)
        conn.execute("DELETE FROM utility_readings WHERE id = ?", (reading_id,))
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
            "INSERT INTO utility_exchanges "
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
        meter_id = _owner(conn, "utility_exchanges", exchange_id)
        _write_dated(
            conn,
            "UPDATE utility_exchanges SET exchange_date = ?, old_final_milli = ?, "
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
        meter_id = _owner(conn, "utility_exchanges", exchange_id)
        conn.execute("DELETE FROM utility_exchanges WHERE id = ?", (exchange_id,))
        _check_series(conn, meter_id)


def reading_to_exchange(conn: sqlite3.Connection, reading_id: int, old_final_milli: int) -> int:
    """Turn a reading into an exchange on its date: the old meter ends at `old_final_milli`."""
    with conn:
        meter_id = _owner(conn, "utility_readings", reading_id)
        day, value = conn.execute(
            "SELECT reading_date, value_milli FROM utility_readings WHERE id = ?", (reading_id,)
        ).fetchone()
        conn.execute("DELETE FROM utility_readings WHERE id = ?", (reading_id,))
        cursor = _write_dated(
            conn,
            "INSERT INTO utility_exchanges "
            "(meter_id, exchange_date, old_final_milli, new_start_milli) VALUES (?, ?, ?, ?)",
            (meter_id, day, old_final_milli, value),
            date.fromisoformat(day),
        )
        _check_series(conn, meter_id)
    return cursor.lastrowid


# Garden conflicts: intervals of a garden meter zeroed against its main meter.


def zero_garden_interval(conn: sqlite3.Connection, meter_id: int, start: date, end: date) -> None:
    with conn:
        _meter_kind(conn, meter_id)
        if _main_meter_id(conn, meter_id) is None:
            raise FieldError("meter", "only a garden meter has zeroed intervals")
        conn.execute(
            "INSERT OR IGNORE INTO utility_garden_zeroed (meter_id, start_date, end_date) "
            "VALUES (?, ?, ?)",
            (meter_id, start.isoformat(), end.isoformat()),
        )


def list_zeroed(conn: sqlite3.Connection, meter_id: int) -> list[tuple[date, date]]:
    _meter_kind(conn, meter_id)
    rows = conn.execute(
        "SELECT start_date, end_date FROM utility_garden_zeroed WHERE meter_id = ? "
        "ORDER BY start_date, end_date",
        (meter_id,),
    ).fetchall()
    return [(date.fromisoformat(start), date.fromisoformat(end)) for start, end in rows]


# Billing periods


def list_periods(conn: sqlite3.Connection, meter_id: int) -> list[Stored[BillingPeriod]]:
    _meter_kind(conn, meter_id)
    return _periods(conn, meter_id)


def add_period(conn: sqlite3.Connection, meter_id: int, period: BillingPeriod) -> int:
    with conn:
        kind = _meter_kind(conn, meter_id)
        _reject_garden_period(conn, meter_id)
        category_id = _category_id(conn, period.category)
        # Checked before writing: a repeated advance date would hit the table's UNIQUE first.
        check_period(period, kind)
        cursor = conn.execute(
            f"""
            INSERT INTO utility_periods ({_PERIOD_COLUMNS}, meter_id, category_id)
            VALUES ({_PERIOD_PLACEHOLDERS}, ?, ?)
            """,
            (*_period_values(period), meter_id, category_id),
        )
        _write_advance_dates(conn, cursor.lastrowid, period)
        _check_periods(conn, meter_id)
    return cursor.lastrowid


def period_settled_cents(conn: sqlite3.Connection, period_id: int) -> int | None:
    row = conn.execute(
        "SELECT settled_cents FROM utility_periods WHERE id = ?", (period_id,)
    ).fetchone()
    if row is None:
        raise UtilityNotFound(period_id)
    return row[0]


def update_period(conn: sqlite3.Connection, period_id: int, period: BillingPeriod) -> None:
    with conn:
        meter_id = _owner(conn, "utility_periods", period_id)
        kind = _meter_kind(conn, meter_id)
        _reject_garden_period(conn, meter_id)
        category_id = _category_id(conn, period.category)
        check_period(period, kind)
        assignments = ", ".join(f"{column} = ?" for column in _PERIOD_COLUMN_NAMES)
        conn.execute(
            f"UPDATE utility_periods SET {assignments}, category_id = ? WHERE id = ?",
            (*_period_values(period), category_id, period_id),
        )
        conn.execute("DELETE FROM utility_advance_dates WHERE period_id = ?", (period_id,))
        _write_advance_dates(conn, period_id, period)
        _check_periods(conn, meter_id)


def delete_period(conn: sqlite3.Connection, period_id: int) -> None:
    with conn:
        _owner(conn, "utility_periods", period_id)
        conn.execute("DELETE FROM utility_advance_dates WHERE period_id = ?", (period_id,))
        conn.execute("DELETE FROM utility_periods WHERE id = ?", (period_id,))


# Owners: the meter a record belongs to, for pages that return to it.


def meter_of_reading(conn: sqlite3.Connection, reading_id: int) -> int:
    return _owner(conn, "utility_readings", reading_id)


def meter_of_exchange(conn: sqlite3.Connection, exchange_id: int) -> int:
    return _owner(conn, "utility_exchanges", exchange_id)


def meter_of_period(conn: sqlite3.Connection, period_id: int) -> int:
    return _owner(conn, "utility_periods", period_id)


# Helpers


def _duplicate_name(name: str) -> FieldError:
    return FieldError("name", f"a meter named {name!r} already exists")


def _meter_kind(conn: sqlite3.Connection, meter_id: int) -> str:
    row = conn.execute("SELECT kind FROM utility_meters WHERE id = ?", (meter_id,)).fetchone()
    if row is None:
        raise UtilityNotFound(meter_id)
    return row[0]


def _main_meter_id(conn: sqlite3.Connection, meter_id: int) -> int | None:
    return conn.execute(
        "SELECT main_meter_id FROM utility_meters WHERE id = ?", (meter_id,)
    ).fetchone()[0]


def _reject_garden_period(conn: sqlite3.Connection, meter_id: int) -> None:
    if _main_meter_id(conn, meter_id) is not None:
        raise FieldError("meter", "a garden meter has no billing periods; its main meter has them")


def _check_main_meter(conn: sqlite3.Connection, meter: Meter) -> None:
    """A garden meter is water and links to an existing water meter that is not a garden."""
    if meter.main_meter_id is None:
        return
    if meter.kind != "water":
        raise FieldError("main_meter_id", "only a water meter can be a garden meter")
    row = conn.execute(
        "SELECT kind, main_meter_id FROM utility_meters WHERE id = ?", (meter.main_meter_id,)
    ).fetchone()
    if row is None:
        raise FieldError("main_meter_id", "the main meter does not exist")
    if row[0] != "water":
        raise FieldError("main_meter_id", "the main meter must be a water meter")
    if row[1] is not None:
        raise FieldError("main_meter_id", "the main meter must not be a garden meter")


def _owner(conn: sqlite3.Connection, table: str, row_id: int) -> int:
    """The meter id a reading, exchange or period belongs to."""
    row = conn.execute(f"SELECT meter_id FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        raise UtilityNotFound(row_id)
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
    """The values of `_PERIOD_COLUMN_NAMES`, in order."""
    return (
        period.start_date.isoformat(),
        period.settlement_date.isoformat(),
        period.base_fee_cents,
        period.unit_price_micro,
        period.state_factor_e4,
        period.calorific_value_e4,
        period.advance_cents,
        period.expected_usage,
        period.settled_cents,
        period.advance_mode,
        period.settlement_debit_days,
        *_charge_values(period.drinking),
        *_charge_values(period.wastewater),
        period.garden_fee_cents,
    )


def _charge_values(charge: Charge | None) -> tuple:
    if charge is None:
        return (None, None, None)
    return (charge.unit_price_micro, charge.base_fee_cents, charge.vat_percent)


def _charge(price: int | None, base_fee: int | None, vat: int | None) -> Charge | None:
    if price is None or base_fee is None or vat is None:
        return None
    return Charge(price, base_fee, vat)


def _write_advance_dates(conn: sqlite3.Connection, period_id: int, period: BillingPeriod) -> None:
    conn.executemany(
        "INSERT INTO utility_advance_dates (period_id, due_date) VALUES (?, ?)",
        [(period_id, day.isoformat()) for day in period.advance_dates],
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
        "SELECT id, reading_date, value_milli FROM utility_readings "
        "WHERE meter_id = ? ORDER BY reading_date",
        (meter_id,),
    ).fetchall()
    return [Stored(id, Reading(date.fromisoformat(day), value)) for id, day, value in rows]


def _exchanges(conn: sqlite3.Connection, meter_id: int) -> list[Stored[Exchange]]:
    rows = conn.execute(
        "SELECT id, exchange_date, old_final_milli, new_start_milli FROM utility_exchanges "
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
    dates = _advance_dates(conn, meter_id)
    return [
        Stored(
            row[0],
            BillingPeriod(
                start_date=date.fromisoformat(row[1]),
                settlement_date=date.fromisoformat(row[2]),
                base_fee_cents=row[3],
                unit_price_micro=row[4],
                state_factor_e4=row[5],
                calorific_value_e4=row[6],
                advance_cents=row[7],
                expected_usage=row[8],
                category=row[9],
                settled_cents=row[10],
                advance_mode=row[11],
                settlement_debit_days=row[12],
                drinking=_charge(*row[13:16]),
                wastewater=_charge(*row[16:19]),
                garden_fee_cents=row[19],
                advance_dates=tuple(dates.get(row[0], ())),
            ),
        )
        for row in rows
    ]


def _advance_dates(conn: sqlite3.Connection, meter_id: int) -> dict[int, list[date]]:
    """Each of the meter's periods' advance dates, sorted, by period id."""
    rows = conn.execute(
        """
        SELECT a.period_id, a.due_date
        FROM utility_advance_dates a JOIN utility_periods p ON p.id = a.period_id
        WHERE p.meter_id = ? ORDER BY a.due_date
        """,
        (meter_id,),
    ).fetchall()
    by_period: dict[int, list[date]] = {}
    for period_id, day in rows:
        by_period.setdefault(period_id, []).append(date.fromisoformat(day))
    return by_period
