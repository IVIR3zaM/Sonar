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
Booking = tuple[date, int]  # booking date, signed cents
Advance = tuple[date, int]  # booking date, cents > 0

CALORIFIC_SCALE = 10**8  # state factor and calorific value are both in ten-thousandths
CENTS_PER_MICRO_EURO_KWH = Fraction(1, 10**4)  # µ€ per kWh to cents per kWh
WHOLE_EURO_CENTS = 100
GRACE_DAYS = 14  # a bill settles late: its last advance and the settlement itself fall this far out
ADVANCES_PER_YEAR = 11


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
    paid_since: date
    advance_count: int
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
    bookings: Iterable[Booking],
    today: date,
) -> MeterStatus | None:
    """The outlook of the period in force today, or None without one."""
    period = current_period(periods, today)
    if period is None:
        return None
    kwh_by_day = daily_kwh(kind, periods, usage)
    previous = _previous_period(periods, period)
    paid_since = _paid_since(period, previous)
    paid_advances = _paid_advances(bookings, previous, paid_since, _paid_until(period, today))
    paid = sum(cents for _, cents in paid_advances)
    latest_advance = paid_advances[-1][0] if paid_advances else None
    advance_count = _advance_count(period)
    due_count = _advances_due(
        period, paid_since, latest_advance, advance_count - len(paid_advances)
    )
    remaining_advances = period.advance_cents * due_count

    # Usage covers [first point, last point), so the last point ends the days so far.
    first_day = max(period.start_date, min(usage, default=date.max))
    end = min(
        max(usage, default=date.min) + timedelta(days=1), period.settlement_date + timedelta(days=1)
    )
    if first_day >= end:
        return MeterStatus(
            None,
            None,
            paid,
            paid_since,
            advance_count,
            None,
            None,
            remaining_advances,
            None,
            None,
            None,
        )

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
        paid_since=paid_since,
        advance_count=advance_count,
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


def _previous_period(
    periods: Sequence[BillingPeriod], period: BillingPeriod
) -> BillingPeriod | None:
    earlier = [other for other in periods if other.settlement_date < period.start_date]
    return max(earlier, key=lambda other: other.settlement_date, default=None)


def _paid_since(period: BillingPeriod, previous: BillingPeriod | None) -> date:
    """The previous bill's own settlement payment lands in the days right after it."""
    if previous is None:
        return period.start_date
    return max(period.start_date, previous.settlement_date + timedelta(days=GRACE_DAYS + 1))


def _paid_until(period: BillingPeriod, today: date) -> date:
    return min(today, period.settlement_date + timedelta(days=GRACE_DAYS))


def _paid_advances(
    bookings: Iterable[Booking], previous: BillingPeriod | None, since: date, until: date
) -> list[Advance]:
    """Debits in the paid window as positive cents, oldest first.

    A debit equal to the previous bill's settled amount is that bill's settlement, not an advance.
    """
    settled = previous.settled_cents if previous else None
    return sorted(
        (booked, -cents)
        for booked, cents in bookings
        if cents < 0
        and since <= booked <= until
        and not (previous and cents == settled and booked > previous.settlement_date)
    )


def _advance_count(period: BillingPeriod) -> int:
    """Eleven advances a year, pro rata by the months the period covers."""
    months = sum(
        (
            Fraction(1, days_in_month(day))
            for day in _days(period.start_date, period.settlement_date)
        ),
        start=Fraction(0),
    )
    return max(1, round_half_up(months * ADVANCES_PER_YEAR / 12))


def _advances_due(
    period: BillingPeriod, paid_since: date, latest_advance: date | None, advances_left: int
) -> int:
    """Advance days after the latest advance (none: from `paid_since`) capped by `advances_left`."""
    advance_day = (latest_advance or paid_since).day
    first = latest_advance + timedelta(days=1) if latest_advance else paid_since
    last = period.settlement_date + timedelta(days=GRACE_DAYS)
    count = 0
    year, month = first.year, first.month
    while date(year, month, 1) <= last:
        due = date(year, month, min(advance_day, calendar.monthrange(year, month)[1]))
        if first <= due <= last:
            count += 1
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return min(count, max(0, advances_left))


def _suggested_advance(still_to_pay: Fraction, due_count: int) -> int | None:
    if due_count == 0:
        return None
    return math.ceil(still_to_pay / due_count / WHOLE_EURO_CENTS) * WHOLE_EURO_CENTS
