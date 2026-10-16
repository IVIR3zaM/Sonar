"""Tests for the utilities service (SPEC §13 Utilities): the meter views the API and pages show."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from sonar.categorization.store import add_category
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.utilities.model import BillingPeriod, Meter, Reading
from sonar.utilities.service import load_utilities, settlement_summaries
from sonar.utilities.store import add_meter, add_period, add_reading
from tests.utilities.test_settlement import (
    WATER_BOOKINGS,
    WATER_TODAY,
    water_periods,
    water_status,
)

TODAY = date(2026, 1, 20)


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _period(**changes) -> BillingPeriod:
    period = BillingPeriod(
        start_date=date(2026, 1, 1),
        settlement_date=date(2026, 12, 31),
        base_fee_cents=0,
        unit_price_micro=100_000,
        state_factor_e4=None,
        calorific_value_e4=None,
        advance_cents=5_000,
        expected_usage=3_650,
        category="Utilities",
    )
    return replace(period, **changes)


def _debit(conn: sqlite3.Connection, tag: str, booked: str, cents: int, category: str | None):
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES ('test', 'acc', ?, ?, ?, 'EUR', 'Utility Co', '', NULL, NULL, NULL, 'raw', ?, 1, ?)
        """,
        (booked, booked, cents, tag, category),
    )


def _meter_with_readings(conn: sqlite3.Connection, **period_changes) -> int:
    meter_id = add_meter(conn, Meter("Power", "electricity"))
    add_period(conn, meter_id, _period(**period_changes))
    add_reading(conn, meter_id, Reading(date(2026, 1, 1), 0))
    add_reading(conn, meter_id, Reading(date(2026, 1, 11), 100_000))
    return meter_id


def test_paid_counts_only_the_period_category_debits_in_the_period(conn):
    _meter_with_readings(conn)
    _debit(conn, "in", "2026-01-05", -10_000, "Utilities")
    _debit(conn, "other-category", "2026-01-06", -7_000, "Groceries")
    _debit(conn, "uncategorized", "2026-01-07", -3_000, None)
    _debit(conn, "credit", "2026-01-08", 2_000, "Utilities")
    _debit(conn, "before", "2025-12-31", -4_000, "Utilities")
    _debit(conn, "future", "2026-01-21", -6_000, "Utilities")

    [view] = load_utilities(conn, TODAY)

    assert view.status is not None
    assert view.status.paid_cents == 10_000


def test_view_lists_the_meter_and_its_rows(conn):
    meter_id = _meter_with_readings(conn)

    [view] = load_utilities(conn, TODAY)

    assert (view.id, view.meter) == (meter_id, Meter("Power", "electricity"))
    assert [r.item.value_milli for r in view.readings] == [0, 100_000]
    assert [p.item.category for p in view.periods] == ["Utilities"]
    assert view.exchanges == []


def test_no_current_period_gives_no_status(conn):
    _meter_with_readings(conn)

    [view] = load_utilities(conn, date(2027, 1, 5))

    assert view.status is None


def test_a_period_without_category_counts_no_advances(conn):
    _meter_with_readings(conn, category=None)
    _debit(conn, "uncategorized", "2026-01-07", -3_000, None)

    [view] = load_utilities(conn, TODAY)

    assert view.status is not None
    assert view.status.paid_cents == 0


def test_chart_months_are_the_full_months_then_the_projected_rest_of_the_cycle(conn):
    meter_id = _meter_with_readings(conn)
    add_reading(conn, meter_id, Reading(date(2026, 2, 1), 310_000))

    [view] = load_utilities(conn, TODAY)

    [january, *rest] = view.chart_months
    assert (january.month, january.kwh, january.projected) == (date(2026, 1, 1), 310, False)
    assert [m.month for m in rest] == [date(2026, month, 1) for month in range(2, 13)]
    assert all(m.projected and m.cycle == "current" for m in rest)


def test_a_meter_without_readings_still_loads(conn):
    add_meter(conn, Meter("Gas", "gas"))

    [view] = load_utilities(conn, TODAY)

    assert view.status is None
    assert view.chart_months == []


def test_settlement_summaries_list_meters_with_a_projection(conn):
    _meter_with_readings(conn)
    add_meter(conn, Meter("Gas", "gas"))  # no period, no summary

    [summary] = settlement_summaries(conn, TODAY)

    assert summary.meter_name == "Power"
    assert summary.settlement_date == date(2026, 12, 31)
    assert summary.settlement_cents is not None
    assert summary.worst_settlement_cents <= summary.settlement_cents
    assert summary.suggested_advance_cents >= 0


def test_settlement_summaries_skip_a_meter_without_usage(conn):
    meter_id = add_meter(conn, Meter("Power", "electricity"))
    add_period(conn, meter_id, _period())

    assert settlement_summaries(conn, TODAY) == []


def test_the_water_pin_meter_in_a_db_gets_the_pure_status(conn):
    add_category(conn, "Water", "fixed")
    meter_id = add_meter(conn, Meter("Water", "water"))
    for period in water_periods():
        add_period(conn, meter_id, period)
    readings = (
        (date(2025, 5, 31), 238_000),
        (date(2025, 12, 31), 355_000),
        (date(2026, 10, 16), 516_000),
    )
    for day, value in readings:
        add_reading(conn, meter_id, Reading(day, value))
    for index, (booked, cents) in enumerate(WATER_BOOKINGS):
        _debit(conn, f"water-{index}", booked.isoformat(), cents, "Water")
    _debit(conn, "other-category", "2026-08-16", -24_000, "Groceries")

    [view] = load_utilities(conn, WATER_TODAY)

    assert view.status == water_status()
    assert (view.status.paid_cents, view.status.settlement_cents) == (96_000, 6903)
    assert view.status.debit_date == date(2027, 2, 24)
