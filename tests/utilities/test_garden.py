import ast
from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

from sonar.utilities.garden import (
    GardenConflict,
    GardenShare,
    garden_conflicts,
    garden_cycle_months,
    garden_usage,
)
from sonar.utilities.model import BillingPeriod, Charge, Reading
from sonar.utilities.usage import continuous_series, daily_usage

DRINKING = Charge(1_140_000, 3600, 7)
WASTEWATER = Charge(3_690_000, 9600, 0)
TODAY = date(2026, 10, 16)


def water_period(start: date, end: date) -> BillingPeriod:
    return BillingPeriod(
        start, end, None, None, None, None, 24_000, 150, "Water", None, DRINKING, WASTEWATER
    )


# The D6 periods of tests/utilities/test_settlement.py.
PERIODS = [
    water_period(date(2025, 5, 31), date(2025, 12, 31)),
    water_period(date(2026, 1, 1), date(2026, 12, 31)),
]


def series_of(*points: tuple[date, int]):
    return continuous_series([Reading(day, value) for day, value in points], [])


def usage_of(*points: tuple[date, int]):
    return daily_usage(series_of(*points))


GARDEN_A = usage_of((date(2025, 5, 31), 0), (date(2025, 12, 31), 21_400), (TODAY, 50_300))
GARDEN_B = usage_of((date(2026, 1, 1), 0), (TODAY, 5_760))


def days(first: date, last: date):
    for offset in range((last - first).days + 1):
        yield first + timedelta(days=offset)


# --- garden_usage ------------------------------------------------------------


def test_garden_a_sums_to_73_halves_over_2026():
    usage = garden_usage(PERIODS, [GARDEN_A])
    assert sum(usage[day] for day in days(date(2026, 1, 1), date(2026, 12, 31))) == Fraction(73, 2)


def test_garden_a_is_a_tenth_every_day_measured_and_projected():
    usage = garden_usage(PERIODS, [GARDEN_A])
    assert all(usage[day] == Fraction(1, 10) for day in days(date(2025, 5, 31), date(2026, 12, 31)))


def test_garden_b_without_history_projects_zero_after_its_last_point():
    usage = garden_usage(PERIODS, [GARDEN_B])
    assert all(usage[day] == Fraction(1, 50) for day in days(date(2026, 1, 1), date(2026, 10, 15)))
    assert all(usage.get(day, 0) == 0 for day in days(date(2026, 10, 16), date(2026, 12, 31)))


def test_gardens_sum_per_day():
    usage = garden_usage(PERIODS, [GARDEN_A, GARDEN_B])
    assert usage[date(2026, 5, 1)] == Fraction(1, 10) + Fraction(1, 50)
    assert usage[date(2025, 6, 1)] == Fraction(1, 10)
    assert usage[date(2026, 11, 1)] == Fraction(1, 10)


def test_days_before_a_gardens_first_point_have_nothing():
    usage = garden_usage(PERIODS, [GARDEN_B])
    assert all(usage.get(day, 0) == 0 for day in days(date(2025, 5, 31), date(2025, 12, 31)))


def test_a_garden_with_no_readings_adds_nothing():
    assert garden_usage(PERIODS, [{}]) == {}
    assert garden_usage(PERIODS, [GARDEN_A, {}]) == garden_usage(PERIODS, [GARDEN_A])


# --- garden_conflicts --------------------------------------------------------

MAIN = series_of((date(2026, 3, 1), 0), (date(2026, 10, 1), 100_000))
JUNE, OCTOBER = date(2026, 6, 1), date(2026, 10, 1)


def test_two_gardens_together_over_the_main_are_one_case_naming_both():
    first = series_of((JUNE, 0), (OCTOBER, 55_000))
    second = series_of((JUNE, 0), (OCTOBER, 5_000))
    assert garden_conflicts(MAIN, {1: first}) == []
    assert garden_conflicts(MAIN, {2: second}) == []
    assert garden_conflicts(MAIN, {1: first, 2: second}) == [
        GardenConflict(
            JUNE,
            OCTOBER,
            2991,
            (GardenShare(1, JUNE, OCTOBER, 55_000), GardenShare(2, JUNE, OCTOBER, 5_000)),
        )
    ]


def test_one_garden_over_the_main_is_one_case_for_its_run():
    garden = series_of((date(2026, 3, 1), 0), (JUNE, 5_000), (OCTOBER, 65_000))
    assert garden_conflicts(MAIN, {7: garden}) == [
        GardenConflict(JUNE, OCTOBER, 2991, (GardenShare(7, JUNE, OCTOBER, 60_000),))
    ]


def test_two_separate_runs_are_two_cases():
    garden = series_of(
        (date(2026, 3, 1), 0),
        (date(2026, 4, 1), 20_000),
        (JUNE, 20_000),
        (date(2026, 7, 1), 40_000),
    )
    assert garden_conflicts(MAIN, {7: garden}) == [
        GardenConflict(
            date(2026, 3, 1),
            date(2026, 4, 1),
            5514,
            (GardenShare(7, date(2026, 3, 1), date(2026, 4, 1), 20_000),),
        ),
        GardenConflict(
            JUNE,
            date(2026, 7, 1),
            5981,
            (GardenShare(7, JUNE, date(2026, 7, 1), 20_000),),
        ),
    ]


def test_one_run_over_two_garden_intervals_is_one_case_with_an_entry_each():
    garden = series_of((JUNE, 0), (date(2026, 8, 1), 40_000), (OCTOBER, 70_000))
    assert garden_conflicts(MAIN, {7: garden}) == [
        GardenConflict(
            JUNE,
            OCTOBER,
            12_991,
            (
                GardenShare(7, JUNE, date(2026, 8, 1), 40_000),
                GardenShare(7, date(2026, 8, 1), OCTOBER, 30_000),
            ),
        )
    ]


def test_an_interval_with_no_conflicting_day_is_no_case():
    garden = series_of((date(2026, 3, 1), 0), (JUNE, 5_000))
    assert garden_conflicts(MAIN, {7: garden}) == []


def test_a_garden_that_used_nothing_on_the_run_is_not_named():
    over = series_of((JUNE, 5_000), (OCTOBER, 65_000))
    idle = series_of((JUNE, 1_000), (OCTOBER, 1_000))
    assert garden_conflicts(MAIN, {1: over, 2: idle}) == [
        GardenConflict(JUNE, OCTOBER, 2991, (GardenShare(1, JUNE, OCTOBER, 60_000),))
    ]


def test_a_garden_with_no_readings_has_no_case():
    assert garden_conflicts(MAIN, {3: []}) == []


# --- garden_cycle_months -----------------------------------------------------


def test_garden_chart_prices_only_the_wastewater_net_and_vat():
    months = {m.month: m for m in garden_cycle_months(PERIODS, GARDEN_A, TODAY)}
    september = months[date(2026, 9, 1)]
    assert (september.kwh, september.cost_cents, september.projected) == (3, 1107, False)


def test_garden_chart_ignores_the_main_garden_fee():
    with_fee = [replace(period, garden_fee_cents=12_000) for period in PERIODS]
    months = {m.month: m for m in garden_cycle_months(with_fee, GARDEN_A, TODAY)}
    september = months[date(2026, 9, 1)]
    assert (september.kwh, september.cost_cents, september.projected) == (3, 1107, False)


# --- architecture ------------------------------------------------------------


def test_garden_imports_no_store_sqlite_or_web_module():
    source = Path(__file__).parents[2] / "src/sonar/utilities/garden.py"
    tree = ast.parse(source.read_text())
    modules = [
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else [a.name for a in node.names]
        )
    ]
    assert not any("store" in m or "sqlite" in m or "web" in m for m in modules)
