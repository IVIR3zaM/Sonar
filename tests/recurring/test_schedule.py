from datetime import date

import pytest

from sonar.recurring.schedule import (
    Occurrence,
    SchedulePeriod,
    next_due_date,
    occurrences,
    pause_after,
    resume_on,
)


def _period(
    starts_on: date,
    amount_cents: int = 1000,
    interval_months: int = 1,
    day: int = 1,
    until: date | None = None,
) -> SchedulePeriod:
    return SchedulePeriod(
        starts_on=starts_on,
        until=until,
        amount_cents=amount_cents,
        interval_months=interval_months,
        day=day,
    )


def test_water_example_pauses_over_winter_and_resumes_with_new_amount():
    water = (_period(date(2025, 11, 15), 24000, 2, 15),)

    paused = pause_after(water, date(2026, 11, 30))
    resumed = resume_on(paused, date(2027, 2, 1), 26000, 2, day=15)

    assert occurrences(resumed, date(2026, 9, 1), date(2027, 5, 31)) == [
        Occurrence(date(2026, 9, 15), 24000),
        Occurrence(date(2026, 11, 15), 24000),
        Occurrence(date(2027, 2, 15), 26000),
        Occurrence(date(2027, 4, 15), 26000),
    ]
    assert occurrences(resumed, date(2026, 12, 1), date(2027, 1, 31)) == []


def test_day_31_clamps_to_month_end_and_returns_to_31():
    periods = (_period(date(2026, 1, 1), day=31),)

    due = [o.due_date for o in occurrences(periods, date(2026, 1, 1), date(2026, 4, 30))]

    assert due == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_day_31_clamps_to_29_in_leap_february():
    periods = (_period(date(2028, 2, 1), day=31),)

    assert occurrences(periods, date(2028, 2, 1), date(2028, 2, 29)) == [
        Occurrence(date(2028, 2, 29), 1000)
    ]


def test_anchor_rolls_to_next_month_when_starts_on_is_past_the_day():
    periods = (_period(date(2026, 3, 20), interval_months=3, day=10),)

    due = [o.due_date for o in occurrences(periods, date(2026, 1, 1), date(2026, 12, 31))]

    assert due == [date(2026, 4, 10), date(2026, 7, 10), date(2026, 10, 10)]


def test_anchor_on_starts_on_itself_counts():
    periods = (_period(date(2026, 3, 10), day=10),)

    assert occurrences(periods, date(2026, 3, 1), date(2026, 3, 31)) == [
        Occurrence(date(2026, 3, 10), 1000)
    ]


def test_occurrences_stop_at_until():
    periods = (_period(date(2026, 1, 1), day=5, until=date(2026, 3, 5)),)

    due = [o.due_date for o in occurrences(periods, date(2026, 1, 1), date(2026, 12, 31))]

    assert due == [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)]


def test_occurrences_are_limited_to_the_window():
    periods = (_period(date(2026, 1, 1), day=5),)

    due = [o.due_date for o in occurrences(periods, date(2026, 3, 5), date(2026, 5, 4))]

    assert due == [date(2026, 3, 5), date(2026, 4, 5)]


def test_overlapping_periods_use_the_latest_started_one():
    older = _period(date(2026, 1, 1), amount_cents=1000, day=1)
    newer = _period(date(2026, 3, 10), amount_cents=2000, day=15)

    result = occurrences((newer, older), date(2026, 1, 1), date(2026, 5, 31))

    assert result == [
        Occurrence(date(2026, 1, 1), 1000),
        Occurrence(date(2026, 2, 1), 1000),
        Occurrence(date(2026, 3, 1), 1000),
        Occurrence(date(2026, 3, 15), 2000),
        Occurrence(date(2026, 4, 15), 2000),
        Occurrence(date(2026, 5, 15), 2000),
    ]


def test_next_due_date_skips_a_payment_already_made_early():
    periods = (_period(date(2026, 1, 1), day=15),)

    assert next_due_date(periods, date(2026, 9, 12), date(2026, 9, 13)) == date(2026, 10, 15)


def test_next_due_date_without_last_paid_is_first_on_or_after_today():
    periods = (_period(date(2026, 1, 1), day=15),)

    assert next_due_date(periods, None, date(2026, 9, 15)) == date(2026, 9, 15)


def test_next_due_date_finds_annual_payment_within_13_months():
    periods = (_period(date(2025, 10, 1), interval_months=12, day=1),)

    assert next_due_date(periods, date(2025, 10, 1), date(2025, 10, 2)) == date(2026, 10, 1)


def test_next_due_date_is_none_after_the_final_until():
    periods = (_period(date(2026, 1, 1), day=15, until=date(2026, 8, 31)),)

    assert next_due_date(periods, date(2026, 8, 15), date(2026, 9, 1)) is None


def test_pause_after_closes_open_periods_and_drops_later_ones():
    open_period = _period(date(2026, 1, 1))
    ends_later = _period(date(2026, 2, 1), until=date(2026, 12, 31))
    ended_before = _period(date(2025, 1, 1), until=date(2025, 6, 30))
    starts_after = _period(date(2026, 7, 1))

    result = pause_after((ended_before, open_period, ends_later, starts_after), date(2026, 6, 30))

    assert result == (
        ended_before,
        _period(date(2026, 1, 1), until=date(2026, 6, 30)),
        _period(date(2026, 2, 1), until=date(2026, 6, 30)),
    )


def test_resume_on_closes_open_period_and_appends_new_one():
    open_period = _period(date(2026, 1, 1), day=15)
    starts_later = _period(date(2026, 8, 1))

    result = resume_on((open_period, starts_later), date(2026, 6, 20), 3000, 3)

    assert result == (
        _period(date(2026, 1, 1), day=15, until=date(2026, 6, 19)),
        _period(date(2026, 6, 20), amount_cents=3000, interval_months=3, day=20),
    )


def test_resume_on_keeps_periods_that_ended_before():
    ended = _period(date(2026, 1, 1), until=date(2026, 3, 31))

    result = resume_on((ended,), date(2026, 5, 1), 3000, 1, day=5)

    assert result == (ended, _period(date(2026, 5, 1), amount_cents=3000, day=5))


@pytest.mark.parametrize(
    ("amount_cents", "interval_months", "day"),
    [(0, 1, 1), (-5, 1, 1), (100, 0, 1), (100, 1, 0), (100, 1, 32)],
)
def test_invalid_periods_raise(amount_cents, interval_months, day):
    with pytest.raises(ValueError):
        resume_on((), date(2026, 1, 1), amount_cents, interval_months, day=day)
    with pytest.raises(ValueError):
        _period(date(2026, 1, 1), amount_cents, interval_months, day)
