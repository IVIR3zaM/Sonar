"""Keep-the-lights-on spending per month and its forecast (SPEC §13 Forecast, Pages).

A month is a salary month as on the Monthly page, or the calendar month
without a salary day. Only complete months count: one that starts before the
first booking or ends after `until` is only partly known. `until` is the
`last_known_day`: the last imported booking, but never after the balance
date, so the dashboard and the Keep the lights on page learn from the same
months. Per month we sum the debits in `lights_on` categories and, for the
chart, in `occasional` ones.

The forecast for the next `days` days uses the latest 3 complete months and
the lights-on figures only: expected = their summed spending ÷ their summed
days × days, so a longer month weighs more; the range runs from the lowest to
the highest monthly daily average × days. Pure functions only; exact
`Fraction` arithmetic keeps cents exact until the final rounding.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

from sonar import monthly
from sonar.categorization import groups
from sonar.monthly import Period
from sonar.transactions import ParsedTransaction

LOOKBACK_MONTHS = 3

Row = tuple[ParsedTransaction, str | None]


@dataclass(frozen=True)
class MonthSpend:
    """One complete month's debit spending, as positive cents."""

    period: Period
    lights_on_by_category: dict[str, int]
    occasional_cents: int

    @property
    def days(self) -> int:
        return (self.period.end - self.period.start).days + 1

    @property
    def lights_on_cents(self) -> int:
        return sum(self.lights_on_by_category.values())

    @property
    def daily_lights_on(self) -> Fraction:
        return Fraction(self.lights_on_cents, self.days)

    @property
    def daily_occasional(self) -> Fraction:
        return Fraction(self.occasional_cents, self.days)

    @property
    def daily_by_category(self) -> dict[str, Fraction]:
        return {
            category: Fraction(cents, self.days)
            for category, cents in self.lights_on_by_category.items()
        }


@dataclass(frozen=True)
class CategoryExpected:
    category: str
    expected_cents: int


@dataclass(frozen=True)
class LightsOnForecast:
    expected_cents: int
    low_cents: int
    high_cents: int
    by_category: tuple[CategoryExpected, ...]
    months_used: tuple[Period, ...]


def last_known_day(rows: Iterable[Row], balance_date: date | None) -> date | None:
    """The last day a complete month may end on, or None without bookings.

    A month is fully known only up to the last imported booking: after it the
    bank export simply stops. Bookings after the balance date are already in
    the balance, so they must not also shape the forecast of what is to come.
    """
    latest_booking = max((tx.booking_date for tx, _ in rows), default=None)
    if latest_booking is None or balance_date is None:
        return latest_booking
    return min(latest_booking, balance_date)


def month_spends(
    rows: Iterable[Row], category_types: dict[str, str], salary_day: int | None, until: date
) -> list[MonthSpend]:
    """The spending of every complete month up to `until`, oldest first."""
    rows = list(rows)
    return [
        month_spend(rows, category_types, period)
        for period in complete_months(rows, salary_day, until)
    ]


def complete_months(rows: Iterable[Row], salary_day: int | None, until: date) -> list[Period]:
    """The months fully inside the booking history and ending by `until`, oldest first."""
    rows = list(rows)
    if not rows:
        return []
    paydays = monthly.salary_paydays(rows)
    first_booking = min(tx.booking_date for tx, _ in rows)
    month = monthly.month_of(first_booking, salary_day, paydays)
    last_month = monthly.month_of(until, salary_day, paydays)
    periods = []
    while month <= last_month:
        periods.append(monthly.period_for(month, salary_day, paydays))
        month = _next_month(month)
    return [p for p in periods if p.start >= first_booking and p.end <= until]


def month_spend(rows: Iterable[Row], category_types: dict[str, str], period: Period) -> MonthSpend:
    """The lights-on (per category) and occasional debits booked in `period`."""
    lights_on: dict[str, int] = defaultdict(int)
    occasional = 0
    for tx, category in rows:
        # Refunds are left out: the forecast predicts spending, not refunds.
        if tx.amount_cents >= 0 or not period.start <= tx.booking_date <= period.end:
            continue
        group = category_types.get(category or "")
        if group == groups.LIGHTS_ON:
            lights_on[category] += -tx.amount_cents
        elif group == groups.OCCASIONAL:
            occasional += -tx.amount_cents
    return MonthSpend(period, dict(lights_on), occasional)


def lights_on_forecast(months: Sequence[MonthSpend], days: int) -> LightsOnForecast | None:
    """Lights-on spending for the next `days` days, or None for "not enough data"."""
    if days < 0:
        raise ValueError(f"days must not be negative, got {days}")
    recent = list(months[-LOOKBACK_MONTHS:])
    if not recent:
        return None
    total_days = sum(m.days for m in recent)
    daily_averages = [m.daily_lights_on for m in recent]
    return LightsOnForecast(
        expected_cents=_cents(Fraction(sum(m.lights_on_cents for m in recent), total_days) * days),
        low_cents=_cents(min(daily_averages) * days),
        high_cents=_cents(max(daily_averages) * days),
        by_category=_expected_by_category(recent, total_days, days),
        months_used=tuple(m.period for m in recent),
    )


def _expected_by_category(
    months: list[MonthSpend], total_days: int, days: int
) -> tuple[CategoryExpected, ...]:
    spent: dict[str, int] = defaultdict(int)
    for month in months:
        for category, cents in month.lights_on_by_category.items():
            spent[category] += cents
    expected = [
        CategoryExpected(category, _cents(Fraction(cents, total_days) * days))
        for category, cents in spent.items()
    ]
    return tuple(sorted(expected, key=lambda e: (-e.expected_cents, e.category)))


def _next_month(month: date) -> date:
    # `month` is always a first of the month, so 32 days later is next month.
    return (month + timedelta(days=32)).replace(day=1)


def _cents(amount: Fraction) -> int:
    # Half a cent rounds up; floor(x + 1/2) is half up because these amounts
    # are never negative.
    return math.floor(amount + Fraction(1, 2))
