"""Month-by-month spending: one month's payments and per-category totals.

With a salary day set, a month is a salary month: it starts on the day the
salary really came in (it often lands a few days before the promised day)
and ends the day before the next one. It is named after the month the salary
pays for, so a salary paid on 26 Aug starts "September". Without a salary day,
a month is the calendar month.

A payment is any debit. Transfer categories (money moved to our own or the
family's accounts) are listed like any other, but kept out of the spent total,
since that money is moved rather than spent. Credits (salary, refunds) are not
payments and are left out. Pure functions only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sonar.payday import payday_in
from sonar.transactions import ParsedTransaction

TRANSFER = "transfer"
SALARY = "Salary"
# How far a real salary payment may land from the promised payday and still
# count as that salary; paydays are a month apart, so windows never overlap.
PAYDAY_TOLERANCE = timedelta(days=10)
# A salary promised after this day of the month is for the next month's budget.
LAST_SAME_MONTH_SALARY_DAY = 15
# The page's filter value for payments without a category; category names
# come from categories.toml, which never uses this spelling.
UNCATEGORIZED = "__uncategorized__"

Row = tuple[ParsedTransaction, str | None]

_MONTH = re.compile(r"(\d{4})-(\d{2})")


@dataclass(frozen=True)
class CategoryTotal:
    category: str | None  # None = uncategorized
    category_type: str | None
    total_cents: int
    count: int

    @property
    def key(self) -> str:
        """The value that selects this category in `only_category`."""
        return _key(self.category)


@dataclass(frozen=True)
class Period:
    month: date  # first of the month the period is named after
    start: date
    end: date  # inclusive


@dataclass(frozen=True)
class MonthlySpending:
    period: Period
    payments: tuple[Row, ...]
    by_category: tuple[CategoryTotal, ...]
    spent_cents: int
    transfers_cents: int


def monthly_spending(
    rows: Iterable[Row], category_types: dict[str, str], period: Period
) -> MonthlySpending:
    """The debits booked in `period`, newest first, with totals per category."""
    payments = sorted(
        (
            row
            for row in rows
            if _is_payment(row[0]) and period.start <= row[0].booking_date <= period.end
        ),
        key=lambda row: row[0].booking_date,
        reverse=True,
    )
    by_category = _totals(payments, category_types)
    transfers = sum(c.total_cents for c in by_category if c.category_type == TRANSFER)
    return MonthlySpending(
        period=period,
        payments=tuple(payments),
        by_category=by_category,
        spent_cents=sum(c.total_cents for c in by_category) - transfers,
        transfers_cents=transfers,
    )


def only_category(payments: Iterable[Row], key: str) -> tuple[Row, ...]:
    """The payments in the category `key` names (see `CategoryTotal.key`), in order."""
    return tuple(row for row in payments if _key(row[1]) == key)


def payment_months(
    rows: Iterable[Row], salary_day: int | None, paydays: Sequence[date]
) -> list[date]:
    """Every month with at least one payment, as first-of-month dates, newest first."""
    return sorted(
        {month_of(tx.booking_date, salary_day, paydays) for tx, _ in rows if _is_payment(tx)},
        reverse=True,
    )


def salary_paydays(rows: Iterable[Row]) -> list[date]:
    """The days a salary really came in, oldest first."""
    return sorted(
        tx.booking_date for tx, category in rows if category == SALARY and not _is_payment(tx)
    )


def period_for(month: date, salary_day: int | None, paydays: Sequence[date]) -> Period:
    """The days that make up `month`: a salary month, or the calendar month without a salary day."""
    if salary_day is None:
        return Period(month, month, _next_month(month) - timedelta(days=1))
    start = _payday(month, salary_day, paydays)
    end = _payday(_next_month(month), salary_day, paydays) - timedelta(days=1)
    return Period(month, start, end)


def month_of(day: date, salary_day: int | None, paydays: Sequence[date]) -> date:
    """The month `day` belongs to, as the first of that month."""
    calendar_month = day.replace(day=1)
    if salary_day is None:
        return calendar_month
    # Salary months follow each other without gaps and are shifted from the
    # calendar by less than a month, so one of these three holds `day`.
    for candidate in (_next_month(calendar_month), calendar_month, _previous_month(calendar_month)):
        period = period_for(candidate, salary_day, paydays)
        if period.start <= day <= period.end:
            return candidate
    raise AssertionError(f"no salary month holds {day}")


def adjacent_months(months: list[date], month: date) -> tuple[date | None, date | None]:
    """The nearest older and newer months in `months` (newest first) around `month`."""
    older = next((m for m in months if m < month), None)
    newer = next((m for m in reversed(months) if m > month), None)
    return older, newer


def parse_month(text: str) -> date:
    """Read "YYYY-MM" as the first of that month, raising ValueError otherwise."""
    match = _MONTH.fullmatch(text)
    if match is None:
        raise ValueError(f"month must look like YYYY-MM, got {text!r}")
    return date(int(match[1]), int(match[2]), 1)


def _totals(payments: list[Row], category_types: dict[str, str]) -> tuple[CategoryTotal, ...]:
    totals: dict[str | None, int] = defaultdict(int)
    counts: dict[str | None, int] = defaultdict(int)
    for tx, category in payments:
        totals[category] += tx.amount_cents
        counts[category] += 1
    # Largest spending first; payments are negative, so ascending cents.
    ordered = sorted(totals, key=lambda category: (totals[category], category or ""))
    return tuple(
        CategoryTotal(
            category, category_types.get(category or ""), totals[category], counts[category]
        )
        for category in ordered
    )


def _payday(month: date, salary_day: int, paydays: Sequence[date]) -> date:
    """The day `month`'s salary came in, or the promised day when none is on record yet."""
    paid_in = _previous_month(month) if salary_day > LAST_SAME_MONTH_SALARY_DAY else month
    promised = payday_in(paid_in.year, paid_in.month, salary_day)
    return next((day for day in paydays if abs(day - promised) <= PAYDAY_TOLERANCE), promised)


def _key(category: str | None) -> str:
    return category or UNCATEGORIZED


def _is_payment(tx: ParsedTransaction) -> bool:
    return tx.amount_cents < 0


def _next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def _previous_month(month: date) -> date:
    return (month.replace(day=1) - timedelta(days=1)).replace(day=1)
