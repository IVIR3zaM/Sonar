from datetime import date

from sonar.cashflow.income import ExpectedIncome, expected_income
from sonar.transactions import ParsedTransaction

SALARY_DAY = 25
ESTIMATE_DATE = date(2026, 10, 7)
TYPES = {"Salary": "income", "Benefits": "income", "Shopping": "lights_on"}


def _credit(booking_date: date, amount_cents: int, category: str = "Salary", who: str = "Employer"):
    tx = ParsedTransaction(
        account="DE00 0000 0000 0000 0000 00",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=who,
        purpose="Credit",
        raw_row="",
    )
    return tx, category


def _monthly_allowance(amount_cents: int = 25500):
    return [
        _credit(date(2026, month, 15), amount_cents, "Benefits", "Family Office")
        for month in (7, 8, 9)
    ]


def _expected(rows) -> ExpectedIncome | None:
    return expected_income(rows, TYPES, SALARY_DAY, ESTIMATE_DATE)


def test_worked_example_adds_lowest_salary_and_recurring_income():
    rows = [
        _credit(date(2026, 6, 25), 300000),
        _credit(date(2026, 7, 24), 320000),
        _credit(date(2026, 7, 27), 10000),
        _credit(date(2026, 8, 22), 310000),
        _credit(date(2026, 9, 25), 400000),  # current cycle: not complete yet
        _credit(date(2026, 8, 3), 9000),  # 10 days from payday: not salary
        _credit(date(2026, 8, 25), 50000, "Shopping", "Refund"),
        *_monthly_allowance(),
    ]

    assert _expected(rows) == ExpectedIncome(
        salary_cents=300000, recurring_cents=25500, total_cents=325500
    )


def test_lowest_salary_of_three_different_cycles_is_expected():
    rows = [
        _credit(date(2026, 6, 25), 330000),
        _credit(date(2026, 7, 24), 290000),
        _credit(date(2026, 8, 25), 310000),
    ]

    assert _expected(rows).salary_cents == 290000


def test_lowest_salary_skips_cycles_without_salary():
    rows = [_credit(date(2026, 7, 24), 320000)]

    assert _expected(rows).salary_cents == 320000


def test_quarterly_income_counts_a_third_rounded_half_up_on_the_total():
    quarterly = [
        _credit(date(2026, month, 15), 10001, "Benefits", "Tax Office") for month in (1, 4, 7)
    ]
    rows = [_credit(date(2026, 8, 25), 300000), *quarterly]

    result = _expected(rows)

    assert result is not None
    assert result.recurring_cents == 3334  # 10001 / 3 = 3333.67


def test_exact_half_cent_rounds_up():
    half_yearly = [
        _credit(date(2026, month, 15), 12003, "Benefits", "Tax Office") for month in (1, 7)
    ]
    rows = [_credit(date(2026, 8, 25), 300000), *half_yearly]

    result = _expected(rows)

    assert result is not None
    assert result.recurring_cents == 2001  # 12003 / 6 = 2000.5


def test_credit_exactly_seven_days_from_payday_counts_and_eight_does_not():
    on_edge = [_credit(date(2026, 9, 1), 100000)]  # payday 2026-08-25 + 7
    beyond = [_credit(date(2026, 9, 2), 100000)]  # payday 2026-08-25 + 8

    assert _expected(on_edge).salary_cents == 100000
    assert _expected(beyond) is None


def test_salary_booked_before_payday_counts_for_that_paydays_cycle():
    rows = [
        _credit(date(2026, 8, 23), 200000),  # payday - 2: the 08-25 cycle
        _credit(date(2026, 10, 3), 900000),  # payday - 2 of the next payday: not complete
    ]

    assert _expected(rows).salary_cents == 200000


def test_no_salary_credits_gives_none_even_with_recurring_income():
    assert _expected(_monthly_allowance()) is None


def test_no_rows_gives_none():
    assert _expected([]) is None
