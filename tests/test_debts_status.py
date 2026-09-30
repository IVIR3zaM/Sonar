from datetime import date

from sonar.debts import (
    Installment,
    Loan,
    LoanStatus,
    MatchRule,
    debt_schedule,
    installment_status,
    loan_status,
)
from sonar.recurring.schedule import SchedulePeriod, occurrences
from sonar.transactions import ParsedTransaction


def _tx(
    amount_cents: int,
    booking_date: date,
    counterparty: str = "Sofa Store",
    mandate_ref: str | None = None,
) -> ParsedTransaction:
    return ParsedTransaction(
        account="DE00 0000 0000 0000 0000 00",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=counterparty,
        purpose="",
        raw_row="",
        mandate_ref=mandate_ref,
    )


# --- loan_status ------------------------------------------------------------


def test_loan_status_projects_balance_and_counts_payments_after_the_statement() -> None:
    loan = Loan(
        name="Car loan",
        balance_cents=500_000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-1"),
    )
    txs = [
        _tx(
            -100_000, date(2026, 6, 15), mandate_ref="M-1"
        ),  # before the statement: not this loan's payment
        _tx(
            -100_000, date(2026, 6, 30), mandate_ref="M-1"
        ),  # on the statement date: already in the balance
        _tx(-100_000, date(2026, 7, 30), mandate_ref="M-1"),  # after: counts
        _tx(-100_000, date(2026, 8, 30), mandate_ref="M-1"),  # after: counts
        _tx(-500, date(2026, 7, 1), mandate_ref="M-2"),  # non-matching debit
        _tx(100_000, date(2026, 7, 30), mandate_ref="M-1"),  # a credit never matches
    ]
    status = loan_status(loan, txs, today=date(2026, 9, 23))
    assert status == LoanStatus(
        projected_balance_cents=300_000,
        payoff_date=date(2026, 11, 30),
        paid_since_statement_cents=200_000,
        paid_off=False,
    )


def test_loan_status_paid_off_when_projected_balance_reaches_zero() -> None:
    loan = Loan(
        name="Small loan",
        balance_cents=100_000,
        balance_as_of=date(2026, 1, 15),
        rate_cents=50_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-2"),
    )
    status = loan_status(loan, [], today=date(2026, 9, 23))
    assert status.projected_balance_cents == 0
    assert status.paid_off
    assert status.payoff_date == date(2026, 3, 15)


def test_loan_status_never_paying_off_has_no_payoff_date() -> None:
    # Rate covers only the interest, so the projection never reaches 0 (SPEC §7).
    loan = Loan(
        name="Interest only",
        balance_cents=1_000_000,
        balance_as_of=date(2026, 1, 15),
        rate_cents=10_000,
        interest_bp=1200,
        match=MatchRule("mandate", "M-3"),
    )
    status = loan_status(loan, [], today=date(2026, 9, 23))
    assert status.payoff_date is None
    assert not status.paid_off


# --- debt_schedule ------------------------------------------------------------


def test_debt_schedule_drops_a_paid_off_loan() -> None:
    loan = Loan(
        name="Small loan",
        balance_cents=100_000,
        balance_as_of=date(2026, 1, 15),
        rate_cents=50_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-2"),
    )
    status = loan_status(loan, [], today=date(2026, 9, 23))
    assert debt_schedule(loan, status) == ()


def test_debt_schedule_for_an_open_loan_starts_the_day_after_the_statement() -> None:
    loan = Loan(
        name="Car loan",
        balance_cents=500_000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-1"),
    )
    status = loan_status(loan, [], today=date(2026, 9, 23))
    assert debt_schedule(loan, status) == (
        SchedulePeriod(date(2026, 7, 1), date(2026, 11, 30), 100_000, 1, 30),
    )


def test_debt_schedule_for_a_loan_that_never_pays_off_has_no_end() -> None:
    loan = Loan(
        name="Interest only",
        balance_cents=1_000_000,
        balance_as_of=date(2026, 1, 15),
        rate_cents=10_000,
        interest_bp=1200,
        match=MatchRule("mandate", "M-3"),
    )
    status = loan_status(loan, [], today=date(2026, 9, 23))
    assert debt_schedule(loan, status) == (SchedulePeriod(date(2026, 1, 16), None, 10_000, 1, 15),)


def test_debt_schedule_drops_a_paid_off_installment() -> None:
    inst = Installment(
        name="Sofa",
        total_cents=10_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=1,
        match=MatchRule("counterparty", "Sofa Store"),
    )
    status = installment_status(inst, [_tx(-10_000, date(2026, 1, 5))])
    assert status.paid_off
    assert debt_schedule(inst, status) == ()


def test_debt_schedule_for_an_open_installment_matches_occurrences_until_end_date() -> None:
    inst = Installment(
        name="Sofa",
        total_cents=120_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=12,
        match=MatchRule("counterparty", "Sofa Store"),
    )
    status = installment_status(inst, [])
    assert not status.paid_off
    periods = debt_schedule(inst, status)
    assert periods == (SchedulePeriod(date(2026, 1, 5), date(2026, 12, 5), 10_000, 1, 5),)

    found = occurrences(periods, date(2026, 9, 1), date(2027, 1, 31))
    assert [o.due_date for o in found] == [
        date(2026, 9, 5),
        date(2026, 10, 5),
        date(2026, 11, 5),
        date(2026, 12, 5),
    ]
    assert all(o.amount_cents == 10_000 for o in found)


# --- debt_schedule: final payment -------------------------------------------


def _amounts_by_date(periods: tuple[SchedulePeriod, ...]) -> list[tuple[date, int]]:
    found = occurrences(periods, date(2026, 1, 1), date(2026, 12, 31))
    return [(o.due_date, o.amount_cents) for o in found]


def test_debt_schedule_for_a_loan_ends_with_the_smaller_final_payment() -> None:
    # 100_000 at 30_000 a month: three full payments, then 10_000 clears it.
    loan = Loan(
        name="Small loan",
        balance_cents=100_000,
        balance_as_of=date(2026, 1, 15),
        rate_cents=30_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-4"),
    )
    status = loan_status(loan, [], today=date(2026, 2, 1))
    periods = debt_schedule(loan, status)
    assert periods == (
        SchedulePeriod(date(2026, 1, 16), date(2026, 5, 14), 30_000, 1, 15),
        SchedulePeriod(date(2026, 5, 15), date(2026, 5, 15), 10_000, 1, 15),
    )
    assert _amounts_by_date(periods) == [
        (date(2026, 2, 15), 30_000),
        (date(2026, 3, 15), 30_000),
        (date(2026, 4, 15), 30_000),
        (date(2026, 5, 15), 10_000),
    ]


def test_debt_schedule_for_a_loan_paid_off_in_one_payment_has_only_the_final_period() -> None:
    # The first due date is already the last, so there is no leading period.
    loan = Loan(
        name="Tiny loan",
        balance_cents=5_000,
        balance_as_of=date(2026, 1, 15),
        rate_cents=30_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-5"),
    )
    status = loan_status(loan, [], today=date(2026, 1, 20))
    periods = debt_schedule(loan, status)
    assert periods == (SchedulePeriod(date(2026, 2, 15), date(2026, 2, 15), 5_000, 1, 15),)
    assert _amounts_by_date(periods) == [(date(2026, 2, 15), 5_000)]


def test_debt_schedule_for_a_loan_with_interest_uses_the_amortized_final_payment() -> None:
    # 12% a year on 100_000: interest 1_000, 600, 196 -> final payment 19_796.
    loan = Loan(
        name="Interest loan",
        balance_cents=100_000,
        balance_as_of=date(2026, 1, 15),
        rate_cents=41_000,
        interest_bp=1200,
        match=MatchRule("mandate", "M-6"),
    )
    status = loan_status(loan, [], today=date(2026, 2, 1))
    periods = debt_schedule(loan, status)
    assert periods == (
        SchedulePeriod(date(2026, 1, 16), date(2026, 4, 14), 41_000, 1, 15),
        SchedulePeriod(date(2026, 4, 15), date(2026, 4, 15), 19_796, 1, 15),
    )


def _installment(total_cents: int, rate_cents: int, payments_count: int) -> Installment:
    return Installment(
        name="Sofa",
        total_cents=total_cents,
        rate_cents=rate_cents,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=payments_count,
        match=MatchRule("counterparty", "Sofa Store"),
    )


def test_debt_schedule_for_an_installment_ends_with_the_smaller_remainder() -> None:
    inst = _installment(100_000, 30_000, 4)
    periods = debt_schedule(inst, installment_status(inst, []))
    assert periods == (
        SchedulePeriod(date(2026, 1, 5), date(2026, 4, 4), 30_000, 1, 5),
        SchedulePeriod(date(2026, 4, 5), date(2026, 4, 5), 10_000, 1, 5),
    )
    assert _amounts_by_date(periods) == [
        (date(2026, 1, 5), 30_000),
        (date(2026, 2, 5), 30_000),
        (date(2026, 3, 5), 30_000),
        (date(2026, 4, 5), 10_000),
    ]


def test_debt_schedule_for_an_installment_ends_with_a_larger_remainder() -> None:
    inst = _installment(100_000, 30_000, 3)
    periods = debt_schedule(inst, installment_status(inst, []))
    assert periods == (
        SchedulePeriod(date(2026, 1, 5), date(2026, 3, 4), 30_000, 1, 5),
        SchedulePeriod(date(2026, 3, 5), date(2026, 3, 5), 40_000, 1, 5),
    )


def test_debt_schedule_for_an_installment_with_no_remainder_keeps_the_rate() -> None:
    # 5 x 30_000 overshoots 100_000, so the remainder is not positive and the
    # plan's own rate is the best guess for the last payment.
    inst = _installment(100_000, 30_000, 5)
    periods = debt_schedule(inst, installment_status(inst, []))
    assert periods == (SchedulePeriod(date(2026, 1, 5), date(2026, 5, 5), 30_000, 1, 5),)


def test_debt_schedule_for_a_single_installment_payment_has_only_the_final_period() -> None:
    inst = _installment(5_000, 30_000, 1)
    periods = debt_schedule(inst, installment_status(inst, []))
    assert periods == (SchedulePeriod(date(2026, 1, 5), date(2026, 1, 5), 5_000, 1, 5),)
