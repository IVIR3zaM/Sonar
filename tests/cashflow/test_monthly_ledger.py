from datetime import date

import pytest

from sonar.cashflow.monthly import LedgerLine, Period, Upcoming, ledger, monthly_spending
from sonar.categorization.groups import FIXED, INCOME, LIGHTS_ON, OCCASIONAL, TRANSFER
from sonar.transactions import ParsedTransaction

PERIOD = Period(date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 30))
CATEGORIES = {
    "Salary": INCOME,
    "Bonus": INCOME,
    "Allowance": INCOME,
    "Rent": FIXED,
    "Food": LIGHTS_ON,
    "Dining": OCCASIONAL,
    "Transfers": TRANSFER,
}


def transaction(amount: int, day: date = date(2026, 9, 10)) -> ParsedTransaction:
    return ParsedTransaction(
        account="Test account",
        booking_date=day,
        value_date=day,
        amount_cents=amount,
        currency="EUR",
        counterparty="Test merchant",
        purpose="Test payment",
        raw_row="",
    )


def spending():
    return monthly_spending(
        [
            (transaction(10_000), "Salary"),
            (transaction(1_000), "Bonus"),
            (transaction(-6_000), "Rent"),
            (transaction(-2_000), "Food"),
            (transaction(-3_000), "Dining"),
            (transaction(-500), None),
            (transaction(-900), "Transfers"),
        ],
        CATEGORIES,
        PERIOD,
    )


def test_income_categories_sum_only_positive_credits_inside_the_period():
    rows = [
        (transaction(2_000, PERIOD.start), "Salary"),
        (transaction(3_000, PERIOD.end), "Salary"),
        (transaction(1_000), "Bonus"),
        (transaction(1_000), "Allowance"),
        (transaction(-500), "Salary"),
        (transaction(0), "Salary"),
        (transaction(9_000, date(2026, 8, 31)), "Salary"),
        (transaction(9_000, date(2026, 10, 1)), "Salary"),
        (transaction(9_000), "Food"),
        (transaction(9_000), "Transfers"),
        (transaction(9_000), None),
    ]
    result = monthly_spending(iter(rows), CATEGORIES, PERIOD)

    assert result.income_by_category == (("Salary", 5_000), ("Allowance", 1_000), ("Bonus", 1_000))
    assert result.income_cents == sum(amount for _, amount in result.income_by_category) == 7_000


def test_ledger_without_upcoming_preserves_paid_figures_and_residual():
    paid = spending()
    result = ledger(paid)

    assert result.upcoming is None
    assert result.income == (LedgerLine("Salary", 10_000, 0), LedgerLine("Bonus", 1_000, 0))
    assert result.income_cents == 11_000
    assert result.fixed.paid_cents == result.fixed.total_cents == -6_000
    assert result.lights_on.paid_cents == result.lights_on.total_cents == -2_000
    assert result.occasional.paid_cents == result.occasional.total_cents == -3_000
    assert result.uncategorized.paid_cents == result.uncategorized.total_cents == -500
    assert result.spent.paid_cents == result.spent.total_cents == -11_500
    assert all(
        line.upcoming_cents == 0
        for line in (
            result.fixed,
            result.lights_on,
            result.occasional,
            result.uncategorized,
            result.spent,
        )
    )
    assert result.possible_residual_cents == 3_000
    assert result.actual_residual_cents == paid.residual_cents == -500


def test_upcoming_merges_income_and_adds_spending_to_residuals():
    upcoming = Upcoming(
        date(2026, 9, 11),
        PERIOD.end,
        -7_000,
        -4_000,
        (("Bonus", 10_000), ("Allowance", 11_000), ("Salary", 2_000)),
    )
    result = ledger(spending(), upcoming)

    assert result.upcoming is upcoming
    assert result.income == (
        LedgerLine("Salary", 10_000, 2_000),
        LedgerLine("Allowance", 0, 11_000),
        LedgerLine("Bonus", 1_000, 10_000),
    )
    assert result.income_cents == 34_000
    assert result.fixed.upcoming_cents == -7_000
    assert result.fixed.total_cents == -13_000
    assert result.lights_on.upcoming_cents == -4_000
    assert result.lights_on.total_cents == -6_000
    assert result.occasional.upcoming_cents == result.uncategorized.upcoming_cents == 0
    assert result.spent.paid_cents == -11_500
    assert result.spent.upcoming_cents == -11_000
    assert result.spent.total_cents == -22_500
    assert result.possible_residual_cents == 15_000
    assert result.actual_residual_cents == 11_500


def test_upcoming_overspending_keeps_both_residuals_negative():
    result = ledger(spending(), Upcoming(date(2026, 9, 11), PERIOD.end, -4_000, -2_000, ()))

    assert result.possible_residual_cents == -3_000
    assert result.actual_residual_cents == -6_500


def test_empty_ledger_has_zero_totals():
    paid = monthly_spending([], CATEGORIES, PERIOD)
    result = ledger(paid)

    assert paid.income_by_category == result.income == ()
    assert result.income_cents == result.spent.total_cents == 0
    assert result.possible_residual_cents == result.actual_residual_cents == 0


@pytest.mark.parametrize("paid, upcoming, total", [(100, 200, 300), (-100, -200, -300), (0, 0, 0)])
def test_ledger_line_total(paid, upcoming, total):
    assert LedgerLine("Test", paid, upcoming).total_cents == total
