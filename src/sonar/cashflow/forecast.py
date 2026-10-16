"""Forecast: fixed payments due, projected balance and the fixed-cost overview.

Feeds the dashboard (SPEC §9). Pure functions only: `today` is always passed in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sonar.cashflow import payday
from sonar.cashflow.payday import Cycle
from sonar.categorization import groups
from sonar.recurring import schedule
from sonar.recurring.detect import Row
from sonar.recurring.schedule import Occurrence, SchedulePeriod

# The monthly equivalent averages the plan over a year, so yearly payments count.
EQUIVALENT_MONTHS = 12
ACTUAL_CYCLES = 6
FORECAST_CYCLES = 6


@dataclass(frozen=True)
class SupplierDates:
    """A utility schedule a recurring payment follows inside [start, end] (SPEC §13 Utilities)."""

    start: date
    end: date
    dates: tuple[date, ...]  # every scheduled date of the span
    remaining: tuple[date, ...]  # the unpaid ones after the estimate date
    amount_cents: int


@dataclass(frozen=True)
class FixedSource:
    name: str
    periods: tuple[SchedulePeriod, ...]
    last_paid_date: date | None
    # Set when the payment is linked to a meter's schedule: it rules the span.
    supplier: SupplierDates | None = None


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
class CycleCost:
    """Fixed costs of one pay cycle: what is booked and what is still expected."""

    start: date
    end: date
    kind: Literal["actual", "current", "forecast"]
    booked_cents: int
    forecast_cents: int

    @property
    def total_cents(self) -> int:
        return self.booked_cents + self.forecast_cents


@dataclass(frozen=True)
class FixedCosts:
    monthly_equivalent_cents: int
    rows: tuple[FixedCostRow, ...]
    cycles: tuple[CycleCost, ...]


def fixed_due(sources: tuple[FixedSource, ...], start: date, end: date) -> list[DueItem]:
    """Fixed payments still expected within [start, end]."""
    items = [
        DueItem(source.name, occurrence.due_date, occurrence.amount_cents)
        for source in sources
        for occurrence in _still_due(source, start, end)
    ]
    return sorted(items, key=lambda item: (item.due_date, item.name))


def next_due(source: FixedSource, today: date) -> date | None:
    """A linked source's first remaining date, else its own cadence's next after the span."""
    supplier = source.supplier
    if supplier is None:
        return schedule.next_due_date(source.periods, source.last_paid_date, today)
    upcoming = min((day for day in supplier.remaining if day >= today), default=None)
    if upcoming is not None:
        return upcoming
    after_span = max(today, supplier.end + timedelta(days=1))
    return schedule.next_due_date(source.periods, source.last_paid_date, after_span)


def pair_advances(
    payments: Sequence[tuple[int, str]], schedules: Sequence[tuple[int, str]]
) -> dict[int, int]:
    """Payment id to schedule id, one-to-one per category in id order; the rest stay unpaired."""
    pairs: dict[int, int] = {}
    for category in {category for _, category in schedules}:
        payment_ids = sorted(key for key, other in payments if other == category)
        schedule_ids = sorted(key for key, other in schedules if other == category)
        pairs.update(zip(payment_ids, schedule_ids, strict=False))
    return pairs


def cycle_costs(
    sources: tuple[FixedSource, ...],
    rows: Sequence[Row],
    category_types: dict[str, str],
    salary_day: int,
    estimate_date: date,
) -> tuple[CycleCost, ...]:
    """Fixed costs per pay cycle: 6 actual, the current and 6 forecast cycles, oldest first."""
    past = tuple(reversed(payday.complete_cycles(estimate_date, salary_day, ACTUAL_CYCLES)))
    current = payday.current_cycle(estimate_date, salary_day)
    ahead = payday.next_cycles(estimate_date, salary_day, FORECAST_CYCLES)
    debits = _fixed_debits(rows, category_types)
    due = fixed_due(sources, estimate_date + timedelta(days=1), ahead[-1].end)

    def booked(cycle: Cycle, until: date) -> int:
        return sum(cents for day, cents in debits if cycle.start <= day <= min(cycle.end, until))

    def forecast(cycle: Cycle) -> int:
        return sum(i.amount_cents for i in due if cycle.start <= i.due_date <= cycle.end)

    return (
        *(CycleCost(c.start, c.end, "actual", booked(c, c.end), 0) for c in past),
        CycleCost(
            current.start, current.end, "current", booked(current, estimate_date), forecast(current)
        ),
        *(CycleCost(c.start, c.end, "forecast", 0, forecast(c)) for c in ahead),
    )


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
    """Monthly equivalent and one row per current payment; no pay cycles yet.

    The pay cycles need a salary day, so the caller adds them with `cycle_costs`.
    """
    total = _year_total(sources, today)
    # Integer round half up; totals are never negative, so this is exact.
    monthly_equivalent = (total * 2 + EQUIVALENT_MONTHS) // (EQUIVALENT_MONTHS * 2)
    rows = [row for source in sources if (row := _row(source, today)) is not None]
    return FixedCosts(
        monthly_equivalent_cents=monthly_equivalent,
        rows=tuple(sorted(rows, key=lambda r: (r.day, r.name))),
        cycles=(),
    )


def fixed_range(rows: Sequence[FixedCostRow]) -> tuple[int, int]:
    """Fixed payments per month as (min, max) over the current rows.

    A month with only the monthly payments is the lightest; a month where every
    payment falls due (quarterly, yearly ones too) is the heaviest.
    """
    low = sum(row.amount_cents for row in rows if row.interval_months <= 1)
    return low, sum(row.amount_cents for row in rows)


def _fixed_debits(rows: Sequence[Row], category_types: dict[str, str]) -> list[tuple[date, int]]:
    return [
        (tx.booking_date, -tx.amount_cents)
        for tx, category in rows
        if tx.amount_cents < 0 and category_types.get(category or "") == groups.FIXED
    ]


def _year_total(sources: tuple[FixedSource, ...], today: date) -> int:
    """Fixed payments due in the 12 calendar months from today's month."""
    first = today.replace(day=1)
    end = schedule.add_months(first, EQUIVALENT_MONTHS, 1) - timedelta(days=1)
    # No last_paid filter: this averages the plan, so a payment already made
    # this month still belongs to this month.
    return sum(
        occurrence.amount_cents for source in sources for occurrence in _planned(source, first, end)
    )


def _planned(source: FixedSource, start: date, end: date) -> list[Occurrence]:
    """Every occurrence in [start, end]: the supplier's dates in its span, own periods outside."""
    own = _own_occurrences(source, start, end)
    if source.supplier is None:
        return own
    return own + _supplier_occurrences(source.supplier, source.supplier.dates, start, end)


def _still_due(source: FixedSource, start: date, end: date) -> list[Occurrence]:
    # A payment booked a few days early or late is already in the balance;
    # same rule as schedule.next_due_date.
    last_paid = source.last_paid_date
    own = [
        occurrence
        for occurrence in _own_occurrences(source, start, end)
        if last_paid is None or occurrence.due_date > last_paid + schedule.TOLERANCE
    ]
    if source.supplier is None:
        return own
    # The supplier's remaining dates are already filtered by the meter's bookings.
    return own + _supplier_occurrences(source.supplier, source.supplier.remaining, start, end)


def _own_occurrences(source: FixedSource, start: date, end: date) -> list[Occurrence]:
    found = schedule.occurrences(source.periods, start, end)
    supplier = source.supplier
    if supplier is None:
        return found
    return [o for o in found if not supplier.start <= o.due_date <= supplier.end]


def _supplier_occurrences(
    supplier: SupplierDates, dates: tuple[date, ...], start: date, end: date
) -> list[Occurrence]:
    return [Occurrence(day, supplier.amount_cents) for day in dates if start <= day <= end]


def _row(source: FixedSource, today: date) -> FixedCostRow | None:
    period = _current_or_next_period(source.periods, today)
    if period is None:
        return None
    # A linked payment shows the advance it pays now; day and interval stay its own.
    amount = period.amount_cents if source.supplier is None else source.supplier.amount_cents
    return FixedCostRow(
        name=source.name,
        day=period.day,
        interval_months=period.interval_months,
        amount_cents=amount,
        next_due=next_due(source, today),
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
