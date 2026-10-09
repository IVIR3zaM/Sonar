"""Schedule periods for recurring payments and the due dates they produce.

A payment's schedule changes over time (SPEC §6, the water example), so it is a
list of periods, each valid from `starts_on` until an optional `until`. Pure
functions only: `today` is always passed in.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date, timedelta

# Payments land up to about a week off their day (weekends, bank processing).
TOLERANCE = timedelta(days=7)
# Long enough to reach the next due date of an annual payment.
SEARCH_MONTHS = 13


@dataclass(frozen=True)
class SchedulePeriod:
    starts_on: date
    until: date | None
    amount_cents: int  # positive = money out
    interval_months: int
    day: int

    def __post_init__(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError(f"amount must be positive, got {self.amount_cents}")
        if self.interval_months < 1:
            raise ValueError(f"interval must be at least 1 month, got {self.interval_months}")
        if not 1 <= self.day <= 31:
            raise ValueError(f"day must be within 1..31, got {self.day}")

    def is_valid_on(self, d: date) -> bool:
        return self.starts_on <= d and (self.until is None or d <= self.until)


@dataclass(frozen=True)
class ScheduleStatus:
    kind: str  # "paused" (on = resume date) or "ended" (on = last until)
    on: date


@dataclass(frozen=True)
class Occurrence:
    due_date: date
    amount_cents: int


def occurrences(periods: tuple[SchedulePeriod, ...], start: date, end: date) -> list[Occurrence]:
    """Due payments within [start, end], each owned by the period valid on its date."""
    found = [
        Occurrence(due, period.amount_cents)
        for index, period in enumerate(periods)
        for due in _due_dates(period, end)
        if start <= due and _owner_index(periods, due) == index
    ]
    return sorted(found, key=lambda o: o.due_date)


def next_due_date(
    periods: tuple[SchedulePeriod, ...], last_paid: date | None, today: date
) -> date | None:
    """First due date from today on that the last payment has not already covered."""
    earliest = today if last_paid is None else max(today, last_paid + TOLERANCE + timedelta(days=1))
    upcoming = occurrences(periods, earliest, add_months(today, SEARCH_MONTHS, today.day))
    return upcoming[0].due_date if upcoming else None


def schedule_status(periods: tuple[SchedulePeriod, ...], today: date) -> ScheduleStatus | None:
    """None while the payment is active or has not started yet, else why it is silent."""
    if not periods or any(p.is_valid_on(today) for p in periods):
        return None
    later_starts = [p.starts_on for p in periods if p.starts_on > today]
    if later_starts:
        # A payment whose periods all lie ahead is just new, not paused.
        if len(later_starts) == len(periods):
            return None
        return ScheduleStatus("paused", min(later_starts))
    return ScheduleStatus("ended", max(p.until for p in periods if p.until is not None))


def pause_after(periods: tuple[SchedulePeriod, ...], last_date: date) -> tuple[SchedulePeriod, ...]:
    """End the schedule after `last_date`: nothing is due past it."""
    return tuple(
        replace(p, until=last_date) if p.until is None or p.until > last_date else p
        for p in periods
        if p.starts_on <= last_date
    )


def resume_on(
    periods: tuple[SchedulePeriod, ...],
    starts_on: date,
    amount_cents: int,
    interval_months: int,
    day: int | None = None,
) -> tuple[SchedulePeriod, ...]:
    """Start a new open period on `starts_on`, replacing whatever was planned from then on."""
    new_period = SchedulePeriod(
        starts_on=starts_on,
        until=None,
        amount_cents=amount_cents,
        interval_months=interval_months,
        day=starts_on.day if day is None else day,
    )
    day_before = starts_on - timedelta(days=1)
    kept = tuple(
        replace(p, until=day_before) if p.until is None or p.until >= starts_on else p
        for p in periods
        if p.starts_on < starts_on
    )
    return (*kept, new_period)


def _due_dates(period: SchedulePeriod, end: date) -> list[date]:
    # Count months from the anchor instead of stepping from the previous date,
    # so a day-31 payment clamped to Feb 28 returns to the 31st in March.
    anchor = add_months(period.starts_on, 0, period.day)
    if anchor < period.starts_on:
        anchor = add_months(period.starts_on, 1, period.day)
    last = end if period.until is None else min(end, period.until)
    dates = []
    due = anchor
    while due <= last:
        dates.append(due)
        due = add_months(anchor, len(dates) * period.interval_months, period.day)
    return dates


def _owner_index(periods: tuple[SchedulePeriod, ...], d: date) -> int | None:
    # The most recently started period wins where periods overlap.
    valid = [i for i, p in enumerate(periods) if p.is_valid_on(d)]
    return max(valid, key=lambda i: periods[i].starts_on, default=None)


def add_months(base: date, months: int, day: int) -> date:
    month_index = base.year * 12 + base.month - 1 + months
    year, month = divmod(month_index, 12)
    month += 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))
