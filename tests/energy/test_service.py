"""Tests for the energy service (SPEC §13 Energy): the meter views the API and pages show."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.energy.model import BillingPeriod, Meter, Reading
from sonar.energy.service import load_energy
from sonar.energy.store import add_meter, add_period, add_reading

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
        expected_kwh=3_650,
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

    [view] = load_energy(conn, TODAY)

    assert view.status is not None
    assert view.status.paid_cents == 10_000


def test_view_lists_the_meter_and_its_rows(conn):
    meter_id = _meter_with_readings(conn)

    [view] = load_energy(conn, TODAY)

    assert (view.id, view.meter) == (meter_id, Meter("Power", "electricity"))
    assert [r.item.value_milli for r in view.readings] == [0, 100_000]
    assert [p.item.category for p in view.periods] == ["Utilities"]
    assert view.exchanges == []


def test_no_current_period_gives_no_status(conn):
    _meter_with_readings(conn)

    [view] = load_energy(conn, date(2027, 1, 5))

    assert view.status is None


def test_a_period_without_category_counts_no_advances(conn):
    _meter_with_readings(conn, category=None)
    _debit(conn, "uncategorized", "2026-01-07", -3_000, None)

    [view] = load_energy(conn, TODAY)

    assert view.status is not None
    assert view.status.paid_cents == 0


def test_month_figures_are_present_for_fully_covered_months(conn):
    meter_id = _meter_with_readings(conn)
    add_reading(conn, meter_id, Reading(date(2026, 2, 1), 310_000))

    [view] = load_energy(conn, TODAY)

    assert [(f.month, f.kwh) for f in view.month_figures] == [(date(2026, 1, 1), 310)]


def test_a_meter_without_readings_still_loads(conn):
    add_meter(conn, Meter("Gas", "gas"))

    [view] = load_energy(conn, TODAY)

    assert view.status is None
    assert view.month_figures == []
