from datetime import date

import pytest

from sonar.debts import Installment, MatchRule, debt_schedule, installment_status
from sonar.forecast import (
    DueItem,
    FixedCostRow,
    FixedSource,
    MonthTotal,
    Projection,
    fixed_costs,
    fixed_due,
    project,
    traffic_light,
)
from sonar.recurring.schedule import SchedulePeriod, pause_after, resume_on


def _water(last_paid: date | None = date(2026, 9, 15)) -> FixedSource:
    # The SPEC §6 water example: €240 every 2 months, paused after November,
    # resumed in February at €260.
    periods = (SchedulePeriod(date(2025, 11, 15), None, 24000, 2, 15),)
    paused = pause_after(periods, date(2026, 11, 30))
    return FixedSource("Water", resume_on(paused, date(2027, 2, 1), 26000, 2, day=15), last_paid)


def _monthly(
    name: str, amount_cents: int, day: int = 1, last_paid: date | None = None
) -> FixedSource:
    return FixedSource(
        name, (SchedulePeriod(date(2026, 1, 1), None, amount_cents, 1, day),), last_paid
    )


def _insurance() -> FixedSource:
    periods = (SchedulePeriod(date(2026, 3, 1), None, 120000, 12, 1),)
    return FixedSource("Insurance", periods, date(2026, 3, 1))


def _months(*totals: int, start: date = date(2026, 9, 1)) -> tuple[MonthTotal, ...]:
    result = []
    for offset, total in enumerate(totals):
        year, month = divmod(start.year * 12 + start.month - 1 + offset, 12)
        result.append(MonthTotal(date(year, month + 1, 1), total))
    return tuple(result)


def test_fixed_costs_water_example_by_month():
    costs = fixed_costs((_water(),), date(2026, 9, 23))

    # Sep 2026 .. Aug 2027; Sep 15 counts although it is already paid.
    assert costs.months == _months(24000, 0, 24000, 0, 0, 26000, 0, 26000, 0, 26000, 0, 26000)
    # 2 * 24000 + 4 * 26000 = 152000; 152000 / 12 = 12666.67
    assert costs.monthly_equivalent_cents == 12667
    assert costs.rows == (FixedCostRow("Water", 15, 2, 24000, date(2026, 11, 15)),)


def test_fixed_costs_rows_sorted_by_day_then_name_and_annual_month_stands_out():
    sources = (_water(), _monthly("Rent", 100000, last_paid=date(2026, 9, 1)), _insurance())

    costs = fixed_costs(sources, date(2026, 9, 23))

    assert costs.rows == (
        FixedCostRow("Insurance", 1, 12, 120000, date(2027, 3, 1)),
        FixedCostRow("Rent", 1, 1, 100000, date(2026, 10, 1)),
        FixedCostRow("Water", 15, 2, 24000, date(2026, 11, 15)),
    )
    assert costs.months[6] == MonthTotal(date(2027, 3, 1), 220000)
    # (152000 + 12 * 100000 + 120000) / 12 = 122666.67
    assert costs.monthly_equivalent_cents == 122667


def test_fixed_costs_paused_row_shows_the_next_period():
    costs = fixed_costs((_water(date(2026, 11, 15)),), date(2026, 12, 10))

    assert costs.rows == (FixedCostRow("Water", 15, 2, 26000, date(2027, 2, 15)),)


def test_fixed_costs_omits_a_source_that_ended_before_today():
    ended = FixedSource(
        "Old gym", (SchedulePeriod(date(2025, 1, 1), date(2026, 8, 31), 3000, 1, 1),), None
    )

    costs = fixed_costs((ended,), date(2026, 9, 23))

    assert costs.rows == ()
    assert costs.months == _months(*[0] * 12)
    assert costs.monthly_equivalent_cents == 0


def test_fixed_costs_monthly_equivalent_rounds_half_up():
    tiny = FixedSource("Tiny", (SchedulePeriod(date(2026, 10, 1), None, 30, 12, 1),), None)

    # 30 / 12 = 2.5, which banker's rounding would turn into 2.
    assert fixed_costs((tiny,), date(2026, 9, 23)).monthly_equivalent_cents == 3


def test_fixed_due_skips_a_payment_already_booked_early():
    assert fixed_due((_water(date(2026, 9, 14)),), date(2026, 9, 10), date(2026, 9, 30)) == []


def test_fixed_due_keeps_a_payment_after_the_tolerance():
    rent = _monthly("Rent", 100000, last_paid=date(2026, 8, 1))

    assert fixed_due((rent,), date(2026, 9, 1), date(2026, 9, 30)) == [
        DueItem("Rent", date(2026, 9, 1), 100000)
    ]


def test_fixed_due_uses_the_final_amount_of_a_debt():
    sofa = Installment(
        name="Sofa",
        total_cents=100000,
        rate_cents=30000,
        interval_months=1,
        first_payment_date=date(2026, 7, 5),
        payments_count=4,
        match=MatchRule("counterparty", "Sofa shop"),
    )
    periods = debt_schedule(sofa, installment_status(sofa, []))
    source = FixedSource("Sofa", periods, None)

    # Payments Jul 5, Aug 5, Sep 5 at 300, then 1000 - 3 * 300 = 100 on Oct 5.
    assert fixed_due((source,), date(2026, 9, 1), date(2026, 11, 30)) == [
        DueItem("Sofa", date(2026, 9, 5), 30000),
        DueItem("Sofa", date(2026, 10, 5), 10000),
    ]


def test_fixed_due_is_empty_when_start_is_after_end():
    rent = _monthly("Rent", 100000)

    assert fixed_due((rent,), date(2026, 9, 30), date(2026, 9, 1)) == []


def test_fixed_due_sorts_by_date_then_name():
    sources = (_monthly("Phone", 2000, day=5), _monthly("Gym", 3000, day=5), _monthly("Rent", 1))

    assert fixed_due(sources, date(2026, 9, 1), date(2026, 9, 30)) == [
        DueItem("Rent", date(2026, 9, 1), 1),
        DueItem("Gym", date(2026, 9, 5), 3000),
        DueItem("Phone", date(2026, 9, 5), 2000),
    ]


def test_project_without_variable_range_uses_fixed_only():
    assert project(100000, 30000, None) == Projection(70000, 70000)


def test_project_with_variable_range():
    assert project(100000, 30000, (40000, 60000)) == Projection(10000, 30000)


@pytest.mark.parametrize(
    "worst,best,limit,expected",
    [
        (-50000, 0, -50000, "green"),
        (-50001, -50000, -50000, "yellow"),
        (-50002, -50001, -50000, "red"),
        (0, 5, 0, "green"),
        (-1, 0, 0, "yellow"),
        (-2, -1, 0, "red"),
    ],
)
def test_traffic_light_boundaries(worst, best, limit, expected):
    assert traffic_light(Projection(worst, best), limit) == expected
