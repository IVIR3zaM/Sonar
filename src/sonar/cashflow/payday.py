"""Salary cycle math (SPEC §8, §9).

Payday is the salary day of the month, moved earlier when it lands on a
weekend (public holidays are out of scope, SPEC §8). A cycle runs from one
payday to the day before the next. Pure functions only: `today` is always
passed in, never read from the clock.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

# How far next_payday/previous_payday look before giving up: the salary day
# adjustment can push a payday into the neighbouring month, so one month of
# slack either side of the starting month is enough to always find one.
_SEARCH_OFFSETS = (0, 1, 2)

SATURDAY = 5
SUNDAY = 6


def payday_in(year: int, month: int, salary_day: int) -> date:
    """The payday for one calendar month.

    Clamp `salary_day` to the month's last day (months don't all have 31
    days), then move a Saturday back 1 day and a Sunday back 2, so payday is
    always a banking day (SPEC §8).
    """
    if not 1 <= salary_day <= 31:
        raise ValueError(f"salary_day must be within 1..31, got {salary_day}")
    last_day = calendar.monthrange(year, month)[1]
    raw = date(year, month, min(salary_day, last_day))
    weekday = raw.weekday()
    if weekday == SATURDAY:
        return raw - timedelta(days=1)
    if weekday == SUNDAY:
        return raw - timedelta(days=2)
    return raw


def next_payday(today: date, salary_day: int) -> date:
    """First payday strictly after `today`."""
    for offset in _SEARCH_OFFSETS:
        year, month = _add_months(today.year, today.month, offset)
        candidate = payday_in(year, month, salary_day)
        if candidate > today:
            return candidate
    # Unreachable: paydays occur roughly monthly, so 3 months of search
    # always finds one strictly after any given day.
    raise ValueError("no payday found in the search window")


def previous_payday(today: date, salary_day: int) -> date:
    """Latest payday on or before `today`."""
    for offset in _SEARCH_OFFSETS:
        year, month = _add_months(today.year, today.month, -offset)
        candidate = payday_in(year, month, salary_day)
        if candidate <= today:
            return candidate
    raise ValueError("no payday found in the search window")


@dataclass(frozen=True)
class Cycle:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1  # inclusive of both ends


def current_cycle(today: date, salary_day: int) -> Cycle:
    """The cycle `today` falls in: previous payday up to the day before the next."""
    start = previous_payday(today, salary_day)
    end = next_payday(today, salary_day) - timedelta(days=1)
    return Cycle(start, end)


def complete_cycles(today: date, salary_day: int, count: int) -> tuple[Cycle, ...]:
    """The `count` full cycles before the current one, most recent first, contiguous."""
    cycles = []
    end = current_cycle(today, salary_day).start - timedelta(days=1)
    for _ in range(count):
        start = previous_payday(end, salary_day)
        cycles.append(Cycle(start, end))
        end = start - timedelta(days=1)
    return tuple(cycles)


def next_cycles(today: date, salary_day: int, count: int) -> tuple[Cycle, ...]:
    """The `count` cycles after the current one, oldest first, contiguous."""
    cycles = []
    start = current_cycle(today, salary_day).end + timedelta(days=1)
    for _ in range(count):
        end = next_payday(start, salary_day) - timedelta(days=1)
        cycles.append(Cycle(start, end))
        start = end + timedelta(days=1)
    return tuple(cycles)


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    # 0-based month arithmetic so it carries across year boundaries cleanly.
    total = (month - 1) + offset
    return year + total // 12, total % 12 + 1
