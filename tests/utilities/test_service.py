"""Tests for the utilities service (SPEC §13 Utilities): the meter views the API and pages show."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from sonar.categorization.store import add_category
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.utilities.garden import garden_cycle_months
from sonar.utilities.model import BillingPeriod, Exchange, Meter, Reading
from sonar.utilities.service import (
    ConflictCase,
    load_utilities,
    meter_cashflows,
    settlement_summaries,
)
from sonar.utilities.store import (
    add_exchange,
    add_meter,
    add_period,
    add_reading,
    zero_garden_interval,
)
from sonar.utilities.usage import continuous_series, daily_usage
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
    assert (view.main_meter_id, view.garden_ids, view.conflicts) == (None, (), ())


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


def _water_pin_meter(conn, periods=None) -> int:
    add_category(conn, "Water", "fixed")
    meter_id = add_meter(conn, Meter("Water", "water"))
    for period in water_periods() if periods is None else periods:
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
    return meter_id


def test_the_water_pin_meter_in_a_db_gets_the_pure_status(conn):
    _water_pin_meter(conn)

    [view] = load_utilities(conn, WATER_TODAY)

    assert view.status == water_status()
    assert (view.status.paid_cents, view.status.settlement_cents) == (96_000, 6903)
    assert view.status.debit_date == date(2027, 2, 24)


def test_settlement_summary_carries_the_debit_date_and_the_schedule(conn):
    _water_pin_meter(conn)

    [summary] = settlement_summaries(conn, WATER_TODAY)

    assert summary.settlement_date == date(2026, 12, 31)
    assert summary.debit_date == date(2027, 2, 24)
    assert summary.advance_mode == "schedule"
    assert summary.remaining_advance_dates == (date(2026, 12, 15),)
    assert summary.remaining_advances_cents == 24_000
    assert summary.suggested_advance_cents is None


def test_settlement_summary_of_a_flexible_meter_has_no_dates(conn):
    _meter_with_readings(conn)

    [summary] = settlement_summaries(conn, TODAY)

    assert summary.advance_mode == "flexible"
    assert summary.remaining_advance_dates == ()
    assert summary.debit_date == summary.settlement_date


def test_meter_cashflows_give_the_schedule_and_the_ended_settled_amount(conn):
    _water_pin_meter(conn)

    [flow] = meter_cashflows(conn, WATER_TODAY)

    assert flow.meter_name == "Water"
    assert flow.category == "Water"
    assert flow.advance_cents == 24_000
    assert flow.advance_dates == (date(2026, 12, 15),)
    assert (flow.ended_debit_date, flow.ended_settlement_cents) == (date(2025, 12, 31), -35_330)


def test_meter_cashflows_carry_the_meter_id_and_the_period_in_force(conn):
    meter_id = _water_pin_meter(conn)

    [flow] = meter_cashflows(conn, WATER_TODAY)

    assert (flow.meter_id, flow.period) == (meter_id, water_periods()[1])


def test_meter_cashflows_of_only_an_ended_period_have_no_period_in_force(conn):
    previous, _ = water_periods()
    _water_pin_meter(conn, [previous])

    [flow] = meter_cashflows(conn, WATER_TODAY)

    assert flow.period is None


def test_meter_cashflows_project_an_ended_period_without_a_settled_amount(conn):
    previous, current = water_periods()
    _water_pin_meter(conn, [replace(previous, settled_cents=None), current])

    [flow] = meter_cashflows(conn, WATER_TODAY)

    assert flow.ended_debit_date == date(2025, 12, 31)
    # Projected as of its settlement date from the booked advances: none were booked in 2025,
    # so every advance of the flexible plan still counts as due.
    assert flow.ended_settlement_cents == 78_399


def test_meter_cashflows_of_a_flexible_meter_have_no_dates(conn):
    _meter_with_readings(conn)

    [flow] = meter_cashflows(conn, TODAY)

    assert (flow.advance_dates, flow.advance_cents) == ((), 5_000)
    assert (flow.ended_debit_date, flow.ended_settlement_cents) == (None, None)


def test_meter_cashflows_skip_a_meter_without_current_or_ended_period(conn):
    add_meter(conn, Meter("Gas", "gas"))

    assert meter_cashflows(conn, TODAY) == []


# --- garden meters -----------------------------------------------------------

GARDEN_READINGS = (
    (date(2025, 5, 31), 0),
    (date(2025, 12, 31), 21_400),
    (date(2026, 10, 16), 50_300),
)
CONFLICT_READING = (date(2026, 10, 16), 200_000)  # 0.618 m3 a day against the main's 0.557


def _garden_meter(conn, main_id: int, readings=GARDEN_READINGS) -> int:
    garden_id = add_meter(conn, Meter("Garden", "water", main_id))
    for day, value in readings:
        add_reading(conn, garden_id, Reading(day, value))
    return garden_id


def _water_with_garden(conn) -> tuple[int, int]:
    main_id = _water_pin_meter(conn, water_periods(garden_fee_cents=1200))
    return main_id, _garden_meter(conn, main_id)


def test_a_main_with_a_garden_meter_and_the_fee_settles_net_of_the_garden(conn):
    _water_with_garden(conn)
    plain = add_meter(conn, Meter("Water plain", "water"))
    for period in water_periods():
        add_period(conn, plain, period)
    for day, value in ((date(2025, 5, 31), 238_000), (date(2025, 12, 31), 355_000)):
        add_reading(conn, plain, Reading(day, value))
    add_reading(conn, plain, Reading(date(2026, 10, 16), 516_000))

    summaries = {s.meter_name: s for s in settlement_summaries(conn, WATER_TODAY)}

    assert set(summaries) == {"Water", "Water plain"}
    assert summaries["Water"].settlement_cents == 19_172
    assert summaries["Water plain"].settlement_cents == 6903


def test_the_garden_meter_is_not_a_cashflow_row(conn):
    _water_with_garden(conn)

    assert [flow.meter_name for flow in meter_cashflows(conn, WATER_TODAY)] == ["Water"]


def test_the_ended_settlement_of_a_main_is_net_of_its_garden(conn):
    previous, current = water_periods()
    _water_pin_meter(conn, [replace(previous, settled_cents=None), current])
    plain_flow = meter_cashflows(conn, WATER_TODAY)[0].ended_settlement_cents
    main_id = conn.execute("SELECT id FROM utility_meters WHERE name = 'Water'").fetchone()[0]
    _garden_meter(conn, main_id)

    [flow] = meter_cashflows(conn, WATER_TODAY)

    assert plain_flow == 78_399
    assert flow.ended_settlement_cents > plain_flow  # a refund grows by the saved wastewater


def test_a_main_view_lists_its_garden_and_a_garden_view_its_main(conn):
    main_id, garden_id = _water_with_garden(conn)

    views = {view.meter.name: view for view in load_utilities(conn, WATER_TODAY)}

    assert views["Water"].garden_ids == (garden_id,)
    assert views["Water"].main_meter_id is None
    assert views["Water"].status.charges[2].name == "garden_fee"
    assert views["Garden"].main_meter_id == main_id
    assert views["Garden"].garden_ids == ()


def test_a_garden_view_has_no_status_and_the_wastewater_only_chart(conn):
    _water_with_garden(conn)
    views = {v.meter.name: v for v in load_utilities(conn, WATER_TODAY)}
    garden, main = views["Garden"], views["Water"]
    usage = daily_usage(continuous_series([r.item for r in garden.readings], []))

    assert garden.status is None
    assert garden.periods == []
    assert garden.chart_months == garden_cycle_months(
        [p.item for p in main.periods], usage, WATER_TODAY
    )
    assert garden.chart_months


def test_a_garden_below_the_main_has_no_case(conn):
    _water_with_garden(conn)

    assert all(view.conflicts == () for view in load_utilities(conn, WATER_TODAY))


def test_a_case_closed_by_a_reading_carries_its_reading_id(conn):
    main_id = _water_pin_meter(conn)
    garden_id = _garden_meter(conn, main_id, GARDEN_READINGS[:2])
    closing = add_reading(conn, garden_id, Reading(*CONFLICT_READING))

    views = {view.meter.name: view for view in load_utilities(conn, WATER_TODAY)}

    expected = ConflictCase(
        garden_id, date(2025, 12, 31), date(2026, 10, 16), 17_600, closing, None, False
    )
    assert views["Garden"].conflicts == (expected,)
    assert views["Water"].conflicts == (expected,)


def test_a_case_closed_by_an_exchange_carries_its_exchange_id(conn):
    main_id = _water_pin_meter(conn)
    garden_id = _garden_meter(conn, main_id, GARDEN_READINGS[:2])
    swap = add_exchange(conn, garden_id, Exchange(CONFLICT_READING[0], CONFLICT_READING[1], 0))

    [case] = {v.meter.name: v for v in load_utilities(conn, WATER_TODAY)}["Garden"].conflicts

    assert (case.reading_id, case.exchange_id, case.zeroed) == (None, swap, False)


def test_a_zeroed_interval_reads_zeroed(conn):
    main_id = _water_pin_meter(conn)
    garden_id = _garden_meter(conn, main_id, GARDEN_READINGS[:2])
    add_reading(conn, garden_id, Reading(*CONFLICT_READING))
    zero_garden_interval(conn, garden_id, date(2025, 12, 31), date(2026, 10, 16))

    [case] = {v.meter.name: v for v in load_utilities(conn, WATER_TODAY)}["Water"].conflicts

    assert case.zeroed is True


def test_a_main_view_holds_the_cases_of_all_its_gardens_and_a_garden_only_its_own(conn):
    main_id = _water_pin_meter(conn)
    first = _garden_meter(conn, main_id, GARDEN_READINGS[:2])
    add_reading(conn, first, Reading(*CONFLICT_READING))
    second = add_meter(conn, Meter("Orchard", "water", main_id))
    for day, value in GARDEN_READINGS[:2]:
        add_reading(conn, second, Reading(day, value))
    add_reading(conn, second, Reading(*CONFLICT_READING))

    views = {view.meter.name: view for view in load_utilities(conn, WATER_TODAY)}

    assert {case.meter_id for case in views["Water"].conflicts} == {first, second}
    assert [case.meter_id for case in views["Garden"].conflicts] == [first]
    assert [case.meter_id for case in views["Orchard"].conflicts] == [second]


def test_gas_and_electricity_views_are_unchanged_beside_a_garden(conn):
    _water_with_garden(conn)
    _meter_with_readings(conn)

    power = next(v for v in load_utilities(conn, WATER_TODAY) if v.meter.name == "Power")

    assert (power.main_meter_id, power.garden_ids, power.conflicts) == (None, (), ())
