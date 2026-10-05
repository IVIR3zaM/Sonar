"""Forecast: fixed payments due, projected balance and the fixed-cost overview.

Feeds the dashboard (SPEC §9). Pure functions only: `today` is always passed in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sonar.recurring import schedule
from sonar.recurring.schedule import SchedulePeriod

MONTHS_SHOWN = 12


@dataclass(frozen=True)
class FixedSource:
    name: str
    periods: tuple[SchedulePeriod, ...]
    last_paid_date: date | None


@dataclass(frozen=True)
class DueItem:
    name: str
    due_date: date
    amount_cents: int


@dataclass(frozen=True)
class Projection:
    worst_cents: int
    best_cents: int


@dataclass(frozen=True)
class FixedCostRow:
    name: str
    day: int
    interval_months: int
    amount_cents: int
    next_due: date | None


@dataclass(frozen=True)
class MonthTotal:
    month: date  # first of the month
    total_cents: int


@dataclass(frozen=True)
class FixedCosts:
    monthly_equivalent_cents: int
    rows: tuple[FixedCostRow, ...]
    months: tuple[MonthTotal, ...]


def fixed_due(sources: tuple[FixedSource, ...], start: date, end: date) -> list[DueItem]:
    """Fixed payments still expected within [start, end]."""
    items = []
    for source in sources:
        for occurrence in schedule.occurrences(source.periods, start, end):
            # A payment booked a few days early or late is already in the
            # balance; same rule as schedule.next_due_date.
            if (
                source.last_paid_date is not None
                and occurrence.due_date <= source.last_paid_date + schedule.TOLERANCE
            ):
                continue
            items.append(DueItem(source.name, occurrence.due_date, occurrence.amount_cents))
    return sorted(items, key=lambda item: (item.due_date, item.name))


def project(
    balance_cents: int,
    fixed_cents: int,
    variable: tuple[int, int] | None,
    inflow_cents: int = 0,
) -> Projection:
    """Balance range after fixed payments, a (low, high) variable range and expected inflows."""
    # Inflows are expected recurring income, so they lift both ends alike.
    known = balance_cents + inflow_cents - fixed_cents
    if variable is None:
        # Too little history for a variable range: show what is known rather
        # than invent a guess, so the range collapses to a single value.
        return Projection(known, known)
    low, high = variable
    return Projection(known - high, known - low)


def traffic_light(p: Projection, limit_cents: int) -> Literal["green", "yellow", "red"]:
    """Traffic light for the projected balance.

    The overdraft limit replaces zero from SPEC §9 (user decision).
    """
    if p.worst_cents >= limit_cents:
        return "green"
    if p.best_cents >= limit_cents:
        return "yellow"
    return "red"


def fixed_costs(sources: tuple[FixedSource, ...], today: date) -> FixedCosts:
    """Monthly equivalent, one row per current payment, and 12 monthly totals."""
    months = _month_totals(sources, today)
    total = sum(m.total_cents for m in months)
    # Integer round half up; totals are never negative, so this is exact.
    monthly_equivalent = (total * 2 + MONTHS_SHOWN) // (MONTHS_SHOWN * 2)
    rows = [row for source in sources if (row := _row(source, today)) is not None]
    return FixedCosts(
        monthly_equivalent_cents=monthly_equivalent,
        rows=tuple(sorted(rows, key=lambda r: (r.day, r.name))),
        months=months,
    )


def _month_totals(sources: tuple[FixedSource, ...], today: date) -> tuple[MonthTotal, ...]:
    first = today.replace(day=1)
    firsts = [schedule.add_months(first, offset, 1) for offset in range(MONTHS_SHOWN)]
    end = schedule.add_months(first, MONTHS_SHOWN, 1) - timedelta(days=1)
    totals: defaultdict[date, int] = defaultdict(int)
    for source in sources:
        # No last_paid filter: this is a calendar view of the plan, so a
        # payment already made this month still belongs to this month.
        for occurrence in schedule.occurrences(source.periods, first, end):
            totals[occurrence.due_date.replace(day=1)] += occurrence.amount_cents
    return tuple(MonthTotal(month, totals[month]) for month in firsts)


def _row(source: FixedSource, today: date) -> FixedCostRow | None:
    period = _current_or_next_period(source.periods, today)
    if period is None:
        return None
    return FixedCostRow(
        name=source.name,
        day=period.day,
        interval_months=period.interval_months,
        amount_cents=period.amount_cents,
        next_due=schedule.next_due_date(source.periods, source.last_paid_date, today),
    )


def _current_or_next_period(
    periods: tuple[SchedulePeriod, ...], today: date
) -> SchedulePeriod | None:
    valid = [p for p in periods if p.is_valid_on(today)]
    if valid:
        # Same tie-break as schedule.occurrences: the latest started period wins.
        return max(valid, key=lambda p: p.starts_on)
    # A paused payment still belongs in the overview, at its resumed terms.
    upcoming = [p for p in periods if p.starts_on > today]
    return min(upcoming, key=lambda p: p.starts_on, default=None)
