"""Energy cost and settlement math (SPEC §13 Energy).

Pure functions over daily usage in meter units. Everything runs in exact fractions;
each figure that is shown is rounded half up once, at the end.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

from sonar.energy.model import BillingPeriod

DailyUsage = dict[date, Fraction]
Advance = tuple[date, int]  # booking date, cents > 0

CALORIFIC_SCALE = 10**8  # state factor and calorific value are both in ten-thousandths
CENTS_PER_MICRO_EURO_KWH = Fraction(1, 10**4)  # µ€ per kWh to cents per kWh
WHOLE_EURO_CENTS = 100


@dataclass(frozen=True)
class MonthFigure:
    month: date  # first day of the calendar month
    kwh: int
    cost_cents: int


@dataclass(frozen=True)
class MeterStatus:
    as_of: date | None
    cost_so_far_cents: int | None
    paid_cents: int
    left_cents: int | None
    projected_cost_cents: int | None
    remaining_advances_cents: int
    settlement_cents: int | None  # positive is a refund
    worst_settlement_cents: int | None
    suggested_advance_cents: int | None


def round_half_up(value: Fraction) -> int:
    return math.floor(value + Fraction(1, 2))


def days_in_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def same_day_last_year(day: date) -> date:
    """The same calendar day a year earlier; 29 February maps to 28 February."""
    if day.month == 2 and day.day == 29:
        return date(day.year - 1, 2, 28)
    return date(day.year - 1, day.month, day.day)


def current_period(periods: Iterable[BillingPeriod], today: date) -> BillingPeriod | None:
    return period_on(periods, today)


def period_on(periods: Iterable[BillingPeriod], day: date) -> BillingPeriod | None:
    for period in periods:
        if period.start_date <= day <= period.settlement_date:
            return period
    return None


def daily_kwh(kind: str, periods: Sequence[BillingPeriod], usage: DailyUsage) -> DailyUsage:
    """kWh per day by the period in force; days outside every period are left out."""
    result: DailyUsage = {}
    for day, units in usage.items():
        period = period_on(periods, day)
        if period is not None:
            result[day] = units * _kwh_per_unit(kind, period)
    return result


def cost(
    kind: str,
    periods: Sequence[BillingPeriod],
    usage: DailyUsage,
    first: date,
    last: date,
) -> int:
    """Cents for the days of [first, last] that have usage and a period in force."""
    return round_half_up(_exact_cost(periods, daily_kwh(kind, periods, usage), first, last))


def month_figures(
    kind: str, periods: Sequence[BillingPeriod], usage: DailyUsage
) -> list[MonthFigure]:
    """Usage and cost of every calendar month whose days all have usage and a period."""
    kwh_by_day = daily_kwh(kind, periods, usage)
    figures = []
    for month in _months_touched(kwh_by_day):
        days = list(_days(month, month.replace(day=days_in_month(month))))
        if all(day in kwh_by_day for day in days):
            figures.append(
                MonthFigure(
                    month,
                    kwh=round_half_up(sum(kwh_by_day[day] for day in days)),
                    cost_cents=round_half_up(_exact_cost(periods, kwh_by_day, days[0], days[-1])),
                )
            )
    return figures


def meter_status(
    kind: str,
    periods: Sequence[BillingPeriod],
    usage: DailyUsage,
    advances: Iterable[Advance],
    today: date,
) -> MeterStatus | None:
    """The outlook of the period in force today, or None without one."""
    period = current_period(periods, today)
    if period is None:
        return None
    kwh_by_day = daily_kwh(kind, periods, usage)
    paid_advances = sorted(
        (booked, cents)
        for booked, cents in advances
        if cents > 0 and period.start_date <= booked <= today
    )
    paid = sum(cents for _, cents in paid_advances)
    latest_advance = paid_advances[-1][0] if paid_advances else None
    due_count = _advances_due(period, latest_advance)
    remaining_advances = period.advance_cents * due_count

    # Usage covers [first point, last point), so the last point ends the days so far.
    first_day = max(period.start_date, min(usage, default=date.max))
    end = min(
        max(usage, default=date.min) + timedelta(days=1), period.settlement_date + timedelta(days=1)
    )
    if first_day >= end:
        return MeterStatus(None, None, paid, None, None, remaining_advances, None, None, None)

    days_so_far = (end - first_day).days
    last_so_far = end - timedelta(days=1)
    cost_so_far = _exact_cost(periods, kwh_by_day, first_day, last_so_far)
    rate = sum(kwh_by_day[day] for day in _days(first_day, last_so_far)) / days_so_far
    remaining_days = list(_days(end, period.settlement_date))

    def projected_at(daily_rate: Fraction) -> Fraction:
        return cost_so_far + _exact_cost_at_rate(period, remaining_days, daily_rate)

    projected = projected_at(rate)
    worst_rate = max(
        rate,
        Fraction(period.expected_kwh, 365),
        _last_year_rate(kwh_by_day, remaining_days),
    )
    projected_cents = round_half_up(projected)
    cost_so_far_cents = round_half_up(cost_so_far)
    return MeterStatus(
        as_of=end,
        cost_so_far_cents=cost_so_far_cents,
        paid_cents=paid,
        left_cents=paid - cost_so_far_cents,
        projected_cost_cents=projected_cents,
        remaining_advances_cents=remaining_advances,
        settlement_cents=paid + remaining_advances - projected_cents,
        worst_settlement_cents=paid + remaining_advances - round_half_up(projected_at(worst_rate)),
        suggested_advance_cents=_suggested_advance(projected - paid, due_count),
    )


def _kwh_per_unit(kind: str, period: BillingPeriod) -> Fraction:
    if kind != "gas":
        return Fraction(1)
    assert period.state_factor_e4 is not None and period.calorific_value_e4 is not None
    return Fraction(period.state_factor_e4 * period.calorific_value_e4, CALORIFIC_SCALE)


def _days(first: date, last: date) -> Iterator[date]:
    for offset in range((last - first).days + 1):
        yield first + timedelta(days=offset)


def _months_touched(kwh_by_day: DailyUsage) -> list[date]:
    months = sorted({day.replace(day=1) for day in kwh_by_day})
    return months


def _fee_per_day(period: BillingPeriod, day: date) -> Fraction:
    return Fraction(period.base_fee_cents, days_in_month(day))


def _exact_cost(
    periods: Sequence[BillingPeriod], kwh_by_day: DailyUsage, first: date, last: date
) -> Fraction:
    total = Fraction(0)
    for day in _days(first, last):
        period = period_on(periods, day)
        if period is not None and day in kwh_by_day:
            total += _energy_cents(period, kwh_by_day[day]) + _fee_per_day(period, day)
    return total


def _energy_cents(period: BillingPeriod, kwh: Fraction) -> Fraction:
    return kwh * period.unit_price_micro * CENTS_PER_MICRO_EURO_KWH


def _exact_cost_at_rate(
    period: BillingPeriod, days: Sequence[date], daily_rate: Fraction
) -> Fraction:
    return sum(
        (_energy_cents(period, daily_rate) + _fee_per_day(period, day) for day in days),
        start=Fraction(0),
    )


def _last_year_rate(kwh_by_day: DailyUsage, days: Sequence[date]) -> Fraction:
    """Mean daily kWh of the same calendar days last year; 0 unless every one is known."""
    if not days:
        return Fraction(0)
    last_year = [kwh_by_day.get(same_day_last_year(day)) for day in days]
    if any(kwh is None for kwh in last_year):
        return Fraction(0)
    return sum(last_year, start=Fraction(0)) / len(days)


def _advances_due(period: BillingPeriod, latest_advance: date | None) -> int:
    """Advance days after the latest advance (none: from the start) up to settlement."""
    advance_day = (latest_advance or period.start_date).day
    count = 0
    year, month = period.start_date.year, period.start_date.month
    while date(year, month, 1) <= period.settlement_date:
        due = date(year, month, min(advance_day, calendar.monthrange(year, month)[1]))
        after_latest = due > latest_advance if latest_advance else due >= period.start_date
        if after_latest and due <= period.settlement_date:
            count += 1
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return count


def _suggested_advance(still_to_pay: Fraction, due_count: int) -> int | None:
    if due_count == 0:
        return None
    return math.ceil(still_to_pay / due_count / WHOLE_EURO_CENTS) * WHOLE_EURO_CENTS
