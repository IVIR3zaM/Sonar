"""Tests for lights_on.py: the Keep-the-lights-on months and forecast (SPEC §13 Forecast)."""

from datetime import date
from fractions import Fraction

import pytest

from sonar import monthly, spending_groups
from sonar.lights_on import (
    CategoryExpected,
    complete_months,
    last_known_day,
    lights_on_forecast,
    month_spends,
)
from sonar.monthly import Period
from sonar.transactions import ParsedTransaction

TYPES = {
    "groceries": spending_groups.LIGHTS_ON,
    "transport": spending_groups.LIGHTS_ON,
    "dining": spending_groups.OCCASIONAL,
    "rent": spending_groups.FIXED,
    "savings": spending_groups.TRANSFER,
    "Salary": spending_groups.INCOME,
}

FEB = Period(date(2026, 2, 1), date(2026, 2, 1), date(2026, 2, 28))
MAR = Period(date(2026, 3, 1), date(2026, 3, 1), date(2026, 3, 31))
APR = Period(date(2026, 4, 1), date(2026, 4, 1), date(2026, 4, 30))

Row = tuple[ParsedTransaction, str | None]


def _tx(booking_date: date, amount_cents: int) -> ParsedTransaction:
    return ParsedTransaction(
        account="DE00 0000 0000 0000 0000 00",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty="Example Shop",
        purpose="",
        raw_row="",
    )


def _debit(day: date, category: str | None, cents: int) -> Row:
    return (_tx(day, -cents), category)


def _groceries_10_12_14() -> list[Row]:
    # Daily averages of exactly 10, 12 and 14 euro in Feb (28), Mar (31) and Apr (30).
    return [
        _debit(FEB.start, "groceries", 28 * 1000),
        _debit(MAR.start, "groceries", 31 * 1200),
        _debit(APR.start, "groceries", 30 * 1400),
    ]


def _forecast(rows: list[Row], days: int, until: date = APR.end, salary_day: int | None = None):
    return lights_on_forecast(month_spends(rows, TYPES, salary_day, until), days)


def test_forecast_uses_day_weighted_average_and_extreme_daily_averages():
    result = _forecast(_groceries_10_12_14(), 5)

    assert result is not None
    assert result.low_cents == 5000
    assert result.high_cents == 7000
    # (28000 + 37200 + 42000) / 89 days * 5 = 6022.47...
    assert result.expected_cents == 6022
    assert result.by_category == (CategoryExpected("groceries", 6022),)
    assert result.months_used == (FEB, MAR, APR)


def test_expected_rounds_half_up():
    # 1 cent over 28 days, forecast for 14 days: exactly half a cent.
    rows = [_debit(date(2026, 2, 1), "groceries", 1)]
    months = month_spends(rows, TYPES, None, date(2026, 2, 28))

    result = lights_on_forecast(months, 14)

    assert result is not None
    assert result.expected_cents == 1  # 14 / 28 = 0.5 rounds up


def test_occasional_debit_shows_in_month_but_not_in_forecast():
    rows = [*_groceries_10_12_14(), _debit(MAR.start, "dining", 6200)]

    months = month_spends(rows, TYPES, None, APR.end)

    assert lights_on_forecast(months, 5) == _forecast(_groceries_10_12_14(), 5)
    march = months[1]
    assert march.occasional_cents == 6200
    assert march.daily_occasional == Fraction(6200, 31)
    assert march.lights_on_cents == 31 * 1200


def test_other_bookings_change_nothing():
    noise = [
        _debit(MAR.start, "rent", 90000),
        (_tx(MAR.start, 5000), "groceries"),  # refund
        _debit(MAR.start, "savings", 20000),
        _debit(MAR.start, None, 3000),
        _debit(MAR.start, "unknown category", 3000),
        (_tx(MAR.start, 300000), "Salary"),
    ]
    rows = [*_groceries_10_12_14(), *noise]

    months = month_spends(rows, TYPES, None, APR.end)

    assert months == month_spends(_groceries_10_12_14(), TYPES, None, APR.end)
    assert lights_on_forecast(months, 5) == _forecast(_groceries_10_12_14(), 5)


def test_month_spend_has_totals_per_category_and_daily_averages():
    rows = [*_groceries_10_12_14(), _debit(APR.end, "transport", 3000)]

    april = month_spends(rows, TYPES, None, APR.end)[2]

    assert april.period == APR
    assert april.days == 30
    assert april.lights_on_by_category == {"groceries": 42000, "transport": 3000}
    assert april.lights_on_cents == 45000
    assert april.occasional_cents == 0
    assert april.daily_lights_on == Fraction(1500)
    assert april.daily_by_category == {"groceries": Fraction(1400), "transport": Fraction(100)}


def test_partial_months_at_either_end_are_excluded():
    rows = [
        _debit(date(2026, 2, 2), "groceries", 1000),
        *_groceries_10_12_14()[1:],
    ]

    assert complete_months(rows, None, date(2026, 4, 29)) == [MAR]


def test_only_the_latest_three_months_are_used():
    jan = Period(date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 31))
    rows = [_debit(jan.start, "groceries", 31 * 50000), *_groceries_10_12_14()]

    months = month_spends(rows, TYPES, None, APR.end)
    result = lights_on_forecast(months, 5)

    assert [m.period for m in months] == [jan, FEB, MAR, APR]
    assert result == _forecast(_groceries_10_12_14(), 5)


def test_months_of_different_length_weight_by_days():
    rows = [
        _debit(date(2026, 1, 1), "groceries", 31000),
        _debit(date(2026, 2, 1), "groceries", 28000),
    ]

    result = _forecast(rows, 10, until=date(2026, 2, 28))

    assert result is not None
    assert (result.expected_cents, result.low_cents, result.high_cents) == (10000, 10000, 10000)


def test_no_complete_month_gives_none():
    assert _forecast([], 5) is None
    assert _forecast([_debit(date(2026, 4, 2), "groceries", 1000)], 5) is None


def test_zero_days_gives_zeros():
    result = _forecast(_groceries_10_12_14(), 0)

    assert result is not None
    assert (result.expected_cents, result.low_cents, result.high_cents) == (0, 0, 0)
    assert result.by_category == (CategoryExpected("groceries", 0),)


def test_negative_days_raise():
    with pytest.raises(ValueError):
        _forecast(_groceries_10_12_14(), -1)


def test_salary_months_follow_real_salary_dates():
    salary = [
        (_tx(date(2026, 1, 27), 300000), "Salary"),
        (_tx(date(2026, 2, 26), 300000), "Salary"),
        (_tx(date(2026, 3, 27), 300000), "Salary"),
        (_tx(date(2026, 4, 28), 300000), "Salary"),
    ]
    rows = [*salary, _debit(date(2026, 2, 10), "groceries", 5000)]
    paydays = monthly.salary_paydays(rows)

    months = complete_months(rows, 28, date(2026, 4, 30))

    assert months == [monthly.period_for(date(2026, month, 1), 28, paydays) for month in (2, 3, 4)]
    assert [(p.start, p.end) for p in months] == [
        (date(2026, 1, 27), date(2026, 2, 25)),
        (date(2026, 2, 26), date(2026, 3, 26)),
        (date(2026, 3, 27), date(2026, 4, 27)),
    ]


def test_group_totals_match_the_monthly_page():
    rows = [
        *_groceries_10_12_14(),
        _debit(MAR.start, "transport", 2500),
        _debit(MAR.end, "dining", 4100),
        _debit(MAR.end, "rent", 90000),
        _debit(MAR.end, None, 700),
        (_tx(MAR.end, 900), "groceries"),
    ]

    for month in month_spends(rows, TYPES, None, APR.end):
        page = monthly.monthly_spending(rows, TYPES, month.period)
        groups = spending_groups.group_totals(page.by_category)
        assert month.lights_on_cents == -groups.lights_on_cents
        assert month.occasional_cents == -groups.occasional_cents


def test_last_known_day_is_the_latest_booking_when_the_balance_is_later():
    rows = [_debit(date(2026, 4, 10), "groceries", 100), _debit(date(2026, 3, 1), "rent", 100)]

    assert last_known_day(rows, date(2026, 4, 30)) == date(2026, 4, 10)


def test_last_known_day_is_the_balance_date_when_it_is_earlier():
    rows = [_debit(date(2026, 4, 10), "groceries", 100)]

    assert last_known_day(rows, date(2026, 4, 5)) == date(2026, 4, 5)


def test_last_known_day_without_a_balance_is_the_latest_booking():
    rows = [_debit(date(2026, 3, 1), "groceries", 100), _debit(date(2026, 4, 10), "rent", 100)]

    assert last_known_day(rows, None) == date(2026, 4, 10)


def test_last_known_day_without_rows_is_none():
    assert last_known_day([], date(2026, 4, 30)) is None
