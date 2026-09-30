from datetime import date

from sonar.debts.amortization import (
    MAX_MONTHS,
    LoanPayment,
    balance_on,
    loan_schedule,
    payoff_date,
)


def _linear_schedule() -> list[LoanPayment]:
    return loan_schedule(100_000, date(2026, 1, 31), 30_000, None)


def test_linear_loan_pays_rate_until_the_rest_and_day_31_returns_after_february():
    assert _linear_schedule() == [
        LoanPayment(date(2026, 2, 28), 30_000, 70_000),
        LoanPayment(date(2026, 3, 31), 30_000, 40_000),
        LoanPayment(date(2026, 4, 30), 30_000, 10_000),
        LoanPayment(date(2026, 5, 31), 10_000, 0),
    ]
    assert payoff_date(_linear_schedule()) == date(2026, 5, 31)


def test_amortized_loan_adds_monthly_interest_before_the_payment():
    schedule = loan_schedule(1_000_000, date(2026, 1, 15), 100_000, 600)

    # 1_000_000 * 6% / 12 = 5_000; 905_000 * 6% / 12 = 4_525 (4_525.0 exactly).
    assert [p.balance_after_cents for p in schedule[:2]] == [905_000, 809_525]
    assert [p.due_date for p in schedule[:2]] == [date(2026, 2, 15), date(2026, 3, 15)]
    assert all(p.amount_cents == 100_000 for p in schedule[:-1])
    assert schedule[-1].amount_cents <= 100_000
    assert schedule[-1].balance_after_cents == 0
    assert payoff_date(schedule) == schedule[-1].due_date


def test_amortized_payments_cover_the_balance_plus_all_interest():
    schedule = loan_schedule(1_000_000, date(2026, 1, 15), 100_000, 600)

    balances_before = [1_000_000] + [p.balance_after_cents for p in schedule[:-1]]
    total_interest = sum(
        p.balance_after_cents + p.amount_cents - before
        for p, before in zip(schedule, balances_before, strict=True)
    )

    assert total_interest > 0
    assert sum(p.amount_cents for p in schedule) == 1_000_000 + total_interest


def test_rate_equal_to_interest_never_pays_off_and_stops_at_max_months():
    as_of = date(2026, 1, 15)
    # 1_000_000 * 12% / 12 = 10_000: the rate only covers the interest.
    schedule = loan_schedule(1_000_000, as_of, 10_000, 1200)

    assert len(schedule) == MAX_MONTHS
    assert payoff_date(schedule) is None
    assert balance_on(1_000_000, schedule, date(2026, 3, 15)) == 1_000_000


def test_rate_below_interest_makes_the_balance_grow():
    schedule = loan_schedule(1_000_000, date(2026, 1, 15), 5_000, 1200)

    assert [p.balance_after_cents for p in schedule[:2]] == [1_005_000, 1_010_050]
    assert payoff_date(schedule) is None


def test_interest_of_exactly_half_a_cent_rounds_up():
    # 100 * 600 = 60_000, which is exactly half of 120_000.
    assert loan_schedule(100, date(2026, 1, 15), 1_000, 600) == [
        LoanPayment(date(2026, 2, 15), 101, 0),
    ]


def test_interest_just_below_half_a_cent_rounds_down():
    # 99 * 600 = 59_400, less than half of 120_000.
    assert loan_schedule(99, date(2026, 1, 15), 1_000, 600) == [
        LoanPayment(date(2026, 2, 15), 99, 0),
    ]


def test_balance_on_before_the_first_payment_is_the_start_balance():
    assert balance_on(100_000, _linear_schedule(), date(2026, 2, 27)) == 100_000


def test_balance_on_a_due_date_includes_that_payment():
    assert balance_on(100_000, _linear_schedule(), date(2026, 2, 28)) == 70_000


def test_balance_on_mid_schedule_is_the_last_step_before_it():
    assert balance_on(100_000, _linear_schedule(), date(2026, 4, 15)) == 40_000


def test_balance_on_after_payoff_is_zero():
    assert balance_on(100_000, _linear_schedule(), date(2027, 1, 1)) == 0


def test_zero_balance_has_no_payments_and_no_payoff_date():
    schedule = loan_schedule(0, date(2026, 1, 15), 10_000, None)

    assert schedule == []
    assert payoff_date(schedule) is None
    assert balance_on(0, schedule, date(2026, 6, 1)) == 0
