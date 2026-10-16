"""Garden water sub-meters (SPEC §13 Utilities): their usage, conflicts and chart.

A garden meter sits behind the main water meter. Its water never reaches the drain, so
its m³ save the wastewater price; this module measures and prices them, nothing more.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from fractions import Fraction

from sonar.utilities.model import BillingPeriod
from sonar.utilities.settlement import (
    ChartMonth,
    DailyUsage,
    cycle_months,
    round_half_up,
    seasonal_daily_kwh,
)
from sonar.utilities.usage import MILLI, Series, daily_usage


@dataclass(frozen=True)
class GardenConflict:
    meter_id: int
    start_date: date
    end_date: date  # the interval's closing reading, exclusive
    excess_milli: int  # garden m³ over the main meter's on the interval's days


def garden_usage(periods: Sequence[BillingPeriod], usages: Iterable[DailyUsage]) -> DailyUsage:
    """The gardens' m³ per day: measured, then projected through every later main period."""
    total: DailyUsage = {}
    for usage in usages:
        for day, units in _measured_and_projected(periods, usage).items():
            total[day] = total.get(day, Fraction(0)) + units
    return total


def _measured_and_projected(periods: Sequence[BillingPeriod], usage: DailyUsage) -> DailyUsage:
    """Expected usage is zeroed so a garden without last year's history projects nothing."""
    if not usage:
        return {}
    as_of = max(usage) + timedelta(days=1)
    days = dict(usage)
    for period in periods:
        if period.settlement_date < as_of:
            continue
        projection = seasonal_daily_kwh("water", replace(period, expected_usage=0), usage, as_of)
        days.update({day: units for day, units in projection.items() if day >= period.start_date})
    return days


def garden_conflicts(main: Series, gardens: Mapping[int, Series]) -> list[GardenConflict]:
    """Garden intervals holding a day where the gardens together measured more than the main.

    Only a garden that used water in the interval is a case; its excess is the gardens'
    total over the main's on those days, since no single garden is to blame.
    """
    excess = _excess_by_day(daily_usage(main), [daily_usage(series) for series in gardens.values()])
    conflicts = []
    for meter_id, series in gardens.items():
        for (start, start_value), (end, end_value) in zip(series, series[1:], strict=False):
            if end_value <= start_value:
                continue
            over = [excess[day] for day in _days_between(start, end) if day in excess]
            if over:
                total = sum(over, start=Fraction(0))
                conflicts.append(GardenConflict(meter_id, start, end, round_half_up(total * MILLI)))
    return conflicts


def _excess_by_day(main: DailyUsage, gardens: list[DailyUsage]) -> DailyUsage:
    """Gardens' m³ over the main's on each day the main measured and the gardens beat it."""
    excess: DailyUsage = {}
    for day, main_units in main.items():
        garden_units = sum((usage.get(day, Fraction(0)) for usage in gardens), start=Fraction(0))
        if garden_units > main_units:
            excess[day] = garden_units - main_units
    return excess


def _days_between(start: date, end: date) -> Iterator[date]:
    """The days of [start, end)."""
    for offset in range((end - start).days):
        yield start + timedelta(days=offset)


def garden_cycle_months(
    periods: Sequence[BillingPeriod], usage: DailyUsage, today: date
) -> list[ChartMonth]:
    """A garden's chart: the main's cycles with only the wastewater m³ price and its VAT."""
    return cycle_months(
        "water", [_wastewater_price_only(period) for period in periods], usage, today
    )


def _wastewater_price_only(period: BillingPeriod) -> BillingPeriod:
    """Garden m³ save the wastewater per m³ only: drinking water and base fees still apply."""
    assert period.drinking is not None and period.wastewater is not None
    return replace(
        period,
        drinking=replace(period.drinking, unit_price_micro=0, base_fee_cents=0),
        wastewater=replace(period.wastewater, base_fee_cents=0),
    )
