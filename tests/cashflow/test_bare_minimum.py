from datetime import date
from types import SimpleNamespace

import pytest

from sonar.cashflow.bare_minimum import (
    DebtEnd,
    bare_minimum,
    cycle_income,
    occasional_per_month,
)
from sonar.cashflow.forecast import CycleCost, DueItem
from sonar.transactions import ParsedTransaction

ESTIMATE_DATE = date(2026, 11, 3)
A = CycleCost(date(2026, 11, 26), date(2026, 12, 23), "forecast", 0, 200_000)
B = CycleCost(date(2026, 12, 24), date(2027, 1, 25), "forecast", 0, 260_000)


def test_maximum_need_uses_forecasts_and_independent_cycle_residuals():
    cycles = (
        CycleCost(date(2026, 9, 26), date(2026, 10, 25), "actual", 999_999, 0),
        CycleCost(date(2026, 10, 26), date(2026, 11, 25), "current", 0, 999_999),
        A,
        B,
    )
    due = (
        DueItem("Loan", B.start, 80_000),
        DueItem("Installment", B.end, 50_000),
        DueItem("Loan", A.start, 30_000),
        DueItem("Outside", date(2027, 1, 26), 999_999),
    )
    result = bare_minimum(cycles, 2_500, due, (), 400_000, 70_000, ESTIMATE_DATE)

    assert result.total_cents == 342_500
    assert result.cycle == result.cycles[1]
    assert result.cycle.start == B.start
    assert result.cycle.end == B.end
    assert result.cycle.days == 33
    assert result.cycle.fixed_cents == 260_000
    assert result.cycle.lights_on_cents == 82_500
    assert result.income_cents == 400_000
    assert result.residual_cents == 57_500
    assert [c.need_cents for c in result.cycles] == [270_000, 342_500]
    assert [c.residual_cents for c in result.cycles] == [130_000, 57_500]
    assert result.cycles[0].days == 28
    assert result.debt_cents == 130_000
    assert result.debt_share_percent == 50
    assert result.occasional_cents == 70_000
    assert result.occasional_margin_cents == -12_500


@pytest.mark.parametrize(
    ("fixed", "debt", "percent"), [(3, 1, 33), (3, 2, 67), (8, 1, 13), (0, 0, 0)]
)
def test_debt_share_rounds_half_up(fixed, debt, percent):
    cycle = CycleCost(A.start, A.end, "forecast", 0, fixed)
    result = bare_minimum((cycle,), 0, (DueItem("Debt", A.start, debt),), (), 100, 0, ESTIMATE_DATE)
    assert result.debt_share_percent == percent


def test_equal_needs_choose_earliest_cycle_even_when_input_is_reversed():
    later = CycleCost(B.start, B.end, "forecast", 0, A.forecast_cents)
    result = bare_minimum((later, A), 0, (), (), 400_000, 0, ESTIMATE_DATE)
    assert result.cycle.start == A.start


def test_debt_ends_include_current_cycle_and_forecast_end_sorted_by_date_and_name():
    drops = (
        DebtEnd("Zulu", "loan", A.start, 100),
        DebtEnd("Before", "loan", ESTIMATE_DATE, 100),
        DebtEnd("Current", "installment", date(2026, 11, 4), 200),
        DebtEnd("After", "loan", date(2027, 1, 26), 300),
        DebtEnd("Alpha", "installment", A.start, 400),
        DebtEnd("Last", "loan", B.end, 500),
    )
    result = bare_minimum((A, B), 0, (), drops, 400_000, 0, ESTIMATE_DATE)
    assert result.drops == (drops[2], drops[4], drops[0], drops[5])


def test_without_forecast_cycle_returns_none():
    current = CycleCost(A.start, A.end, "current", 0, 200_000)
    assert bare_minimum((current,), 0, (), (), 400_000, 0, ESTIMATE_DATE) is None
    assert bare_minimum((), 0, (), (), 400_000, 0, ESTIMATE_DATE) is None


def _row(booked, cents, category="Salary"):
    return (
        ParsedTransaction(
            account="test",
            booking_date=booked,
            value_date=booked,
            amount_cents=cents,
            currency="EUR",
            counterparty="Example employer",
            purpose="Example credit",
            raw_row="",
        ),
        category,
    )


def test_cycle_income_sums_all_income_credits_in_shifted_complete_cycles():
    rows = [
        _row(date(2026, 8, 23), 300_000),
        _row(date(2026, 9, 17), 10_000, "Other income"),
        _row(date(2026, 9, 18), 5_000),
        _row(date(2026, 7, 23), 320_000),
        _row(date(2026, 8, 24), -50_000),
        _row(date(2026, 8, 25), 999_999, "Transfer"),
        _row(date(2026, 10, 18), 1),
        _row(date(2026, 6, 17), 1),
    ]
    types = {"Salary": "income", "Other income": "income", "Transfer": "transfer"}
    assert cycle_income(iter(rows), types, 25, date(2026, 10, 7)) == 310_000


@pytest.mark.parametrize("rows", [[], [_row(date(2026, 8, 23), -100)]])
def test_cycle_income_without_positive_complete_cycle_returns_none(rows):
    assert cycle_income(rows, {"Salary": "income"}, 25, ESTIMATE_DATE) is None


@pytest.mark.parametrize(
    ("amounts", "expected"), [([], 0), ([1, 2], 2), ([999, 1, 2, 2], 2), ([70_000], 70_000)]
)
def test_occasional_average_uses_latest_three_months_and_rounds_half_up(amounts, expected):
    months = [SimpleNamespace(occasional_cents=amount) for amount in amounts]
    assert occasional_per_month(months) == expected
