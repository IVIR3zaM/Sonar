import ast
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

from sonar.utilities.garden import (
    GardenConflict,
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


def test_garden_over_the_main_is_one_case_for_its_interval():
    garden = series_of(
        (date(2026, 3, 1), 0), (date(2026, 6, 1), 5_000), (date(2026, 10, 1), 65_000)
    )
    assert garden_conflicts(MAIN, {7: garden}) == [
        GardenConflict(7, date(2026, 6, 1), date(2026, 10, 1), 2991)
    ]


def test_an_interval_with_no_conflicting_day_is_no_case():
    garden = series_of((date(2026, 3, 1), 0), (date(2026, 6, 1), 5_000))
    assert garden_conflicts(MAIN, {7: garden}) == []


def test_two_gardens_together_over_the_main_are_one_case_each():
    first = series_of((date(2026, 6, 1), 0), (date(2026, 10, 1), 55_000))
    second = series_of((date(2026, 6, 1), 0), (date(2026, 10, 1), 5_000))
    assert garden_conflicts(MAIN, {1: first}) == []
    assert garden_conflicts(MAIN, {2: second}) == []
    assert garden_conflicts(MAIN, {1: first, 2: second}) == [
        GardenConflict(1, date(2026, 6, 1), date(2026, 10, 1), 2991),
        GardenConflict(2, date(2026, 6, 1), date(2026, 10, 1), 2991),
    ]


def test_a_garden_that_used_nothing_in_the_interval_is_no_case():
    over = series_of((date(2026, 6, 1), 5_000), (date(2026, 10, 1), 65_000))
    idle = series_of((date(2026, 6, 1), 1_000), (date(2026, 10, 1), 1_000))
    assert garden_conflicts(MAIN, {1: over, 2: idle}) == [
        GardenConflict(1, date(2026, 6, 1), date(2026, 10, 1), 2991)
    ]


def test_a_garden_with_no_readings_has_no_case():
    assert garden_conflicts(MAIN, {3: []}) == []


# --- garden_cycle_months -----------------------------------------------------


def test_garden_chart_prices_only_the_wastewater_net_and_vat():
    months = {m.month: m for m in garden_cycle_months(PERIODS, GARDEN_A, TODAY)}
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
