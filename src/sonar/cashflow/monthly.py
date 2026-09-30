"""Month-by-month spending: one month's payments and per-category totals.

With a salary day set, a month is a salary month: it starts on the day the
salary really came in (it often lands a few days before the promised day)
and ends the day before the next one. It is named after the month the salary
pays for, so a salary paid on 26 Aug starts "September". Without a salary day,
a month is the calendar month.

A payment is any debit. Transfer categories (money moved to our own or the
family's accounts) are not spending, so they leave `by_category` and get
their own `transfer_totals`, one row per transfer category, netting its
debits against its transfer credits (money moved back) for the whole period,
even though only debits are ever listed as payments in the Payments table.
`transfers_net_cents` is their sum. Other credits (salary, refunds) are not
payments and are left out.
Pure functions only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sonar.cashflow.payday import payday_in
from sonar.categorization.groups import TRANSFER, GroupTotals, group_totals
from sonar.transactions import ParsedTransaction

SALARY = "Salary"
# How far a real salary payment may land from the promised payday and still
# count as that salary; paydays are a month apart, so windows never overlap.
PAYDAY_TOLERANCE = timedelta(days=10)
# A salary promised after this day of the month is for the next month's budget.
LAST_SAME_MONTH_SALARY_DAY = 15
# The page's filter value for payments without a category; category names
# come from the DB (categorization/store.py), which never uses this spelling.
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
    transfer_totals: tuple[CategoryTotal, ...]
    spent_cents: int
    transfers_net_cents: int
    groups: GroupTotals


def monthly_spending(
    rows: Iterable[Row], category_types: dict[str, str], period: Period
) -> MonthlySpending:
    """The debits booked in `period`, newest first, with totals per category."""
    in_period = [row for row in rows if period.start <= row[0].booking_date <= period.end]
    payments = sorted(
        (row for row in in_period if _is_payment(row[0])),
        key=lambda row: row[0].booking_date,
        reverse=True,
    )
    non_transfer_payments = [
        row for row in payments if category_types.get(row[1] or "") != TRANSFER
    ]
    by_category = _totals(non_transfer_payments, category_types)
    # Nets debits and credits, unlike by_category and spent_cents, which stay
    # debits-only: a transfer out and its matching money coming back both
    # count, even though only the debit is ever listed as a payment.
    transfer_totals = _transfer_totals(in_period, category_types)
    return MonthlySpending(
        period=period,
        payments=tuple(payments),
        by_category=by_category,
        transfer_totals=transfer_totals,
        spent_cents=sum(c.total_cents for c in by_category),
        transfers_net_cents=sum(c.total_cents for c in transfer_totals),
        groups=group_totals(by_category),
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


def _transfer_totals(
    in_period: list[Row], category_types: dict[str, str]
) -> tuple[CategoryTotal, ...]:
    """One row per transfer category with a booking in the period, net ascending then name."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for tx, category in in_period:
        if category_types.get(category or "") != TRANSFER:
            continue
        totals[category] += tx.amount_cents
        counts[category] += 1
    ordered = sorted(totals, key=lambda category: (totals[category], category))
    return tuple(
        CategoryTotal(category, TRANSFER, totals[category], counts[category])
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
