"""Tests for payday.py: the salary cycle math behind settings and the
dashboard (SPEC §8, §9).
"""

import calendar
from datetime import date

import pytest

from sonar.cashflow.payday import (
    Cycle,
    complete_cycles,
    current_cycle,
    next_payday,
    payday_in,
    previous_payday,
)


def test_payday_in_moves_saturday_back_one_day():
    assert calendar.weekday(2026, 9, 26) == calendar.SATURDAY
    assert payday_in(2026, 9, 26) == date(2026, 9, 25)


def test_payday_in_moves_sunday_back_two_days():
    assert calendar.weekday(2026, 7, 26) == calendar.SUNDAY
    assert payday_in(2026, 7, 26) == date(2026, 7, 24)


def test_payday_in_keeps_a_weekday_unchanged():
    assert calendar.weekday(2026, 10, 26) == calendar.MONDAY
    assert payday_in(2026, 10, 26) == date(2026, 10, 26)


def test_payday_in_clamps_to_a_30_day_month():
    # April has only 30 days, and the 30th itself is a plain weekday.
    assert calendar.weekday(2026, 4, 30) == calendar.THURSDAY
    assert payday_in(2026, 4, 31) == date(2026, 4, 30)


def test_payday_in_clamps_then_shifts_off_the_weekend():
    # February 2026 has 28 days; clamped day 28 lands on a Saturday.
    assert calendar.weekday(2026, 2, 28) == calendar.SATURDAY
    assert payday_in(2026, 2, 31) == date(2026, 2, 27)


def test_payday_in_can_fall_in_the_previous_month():
    assert calendar.weekday(2026, 8, 1) == calendar.SATURDAY
    assert payday_in(2026, 8, 1) == date(2026, 7, 31)


@pytest.mark.parametrize("salary_day", [0, 32])
def test_payday_in_rejects_out_of_range_day(salary_day):
    with pytest.raises(ValueError):
        payday_in(2026, 9, salary_day)


def test_next_payday_is_this_month_when_still_ahead():
    assert next_payday(date(2026, 9, 23), 26) == date(2026, 9, 25)


def test_next_payday_rolls_over_when_today_is_payday_itself():
    # Payday equal to today is not "strictly after", so it moves a month on.
    assert next_payday(date(2026, 9, 25), 26) == date(2026, 10, 26)


def test_next_payday_needs_the_following_month_when_this_months_has_passed():
    assert next_payday(date(2026, 7, 30), 1) == date(2026, 7, 31)


@pytest.mark.parametrize("salary_day", [0, 32])
def test_next_payday_rejects_out_of_range_day(salary_day):
    with pytest.raises(ValueError):
        next_payday(date(2026, 9, 23), salary_day)


def test_previous_payday_is_this_month_when_already_past():
    assert previous_payday(date(2026, 9, 25), 26) == date(2026, 9, 25)


def test_previous_payday_looks_back_a_month_when_this_months_is_still_ahead():
    assert previous_payday(date(2026, 8, 3), 1) == date(2026, 7, 31)


@pytest.mark.parametrize("salary_day", [0, 32])
def test_previous_payday_rejects_out_of_range_day(salary_day):
    with pytest.raises(ValueError):
        previous_payday(date(2026, 9, 23), salary_day)


def test_cycle_days_counts_both_ends():
    assert Cycle(date(2026, 8, 26), date(2026, 9, 24)).days == 30


def test_current_cycle_runs_from_previous_to_the_day_before_next_payday():
    cycle = current_cycle(date(2026, 9, 23), 26)
    assert cycle == Cycle(date(2026, 8, 26), date(2026, 9, 24))
    assert cycle.days == 30


def test_complete_cycles_are_contiguous_most_recent_first():
    assert complete_cycles(date(2026, 9, 23), 26, 3) == (
        Cycle(date(2026, 7, 24), date(2026, 8, 25)),
        Cycle(date(2026, 6, 26), date(2026, 7, 23)),
        Cycle(date(2026, 5, 26), date(2026, 6, 25)),
    )
