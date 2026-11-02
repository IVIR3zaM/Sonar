from datetime import date

import pytest

from sonar.debts.model import Loan, MatchRule, loan_status
from sonar.transactions import ParsedTransaction


def _tx(amount_cents: int, booking_date: date) -> ParsedTransaction:
    return ParsedTransaction(
        account="DE00 0000 0000 0000 0000 00",
        booking_date=booking_date,
        value_date=booking_date,
        amount_cents=amount_cents,
        currency="EUR",
        counterparty="Example Bank",
        purpose="",
        raw_row="",
        mandate_ref="M-SHARED",
    )


def _loan(rate_cents: int = 10_000, balance_cents: int = 100_000) -> Loan:
    return Loan(
        name="Example loan",
        balance_cents=balance_cents,
        balance_as_of=date(2026, 6, 30),
        rate_cents=rate_cents,
        interest_bp=None,
        match=MatchRule("mandate", "M-SHARED"),
    )


@pytest.mark.parametrize("rate, paid", [(3_214, 6_428), (4_311, 8_622), (2_558, 5_116)])
def test_shared_debits_count_each_loans_scheduled_amount(rate: int, paid: int) -> None:
    txs = [_tx(-10_083, date(2026, 7, 30)), _tx(-10_083, date(2026, 8, 30))]

    status = loan_status(_loan(rate), txs, today=date(2026, 9, 23))

    assert status.paid_since_statement_cents == paid


@pytest.mark.parametrize(
    "amount, booked",
    [
        (-9_999, date(2026, 7, 30)),
        (-20_000, date(2026, 7, 22)),
        (-20_000, date(2026, 8, 7)),
        (-10_000, date(2026, 9, 23)),
    ],
)
def test_unrelated_and_not_yet_due_debits_add_nothing(amount: int, booked: date) -> None:
    status = loan_status(_loan(), [_tx(amount, booked)], today=date(2026, 9, 23))

    assert status.paid_since_statement_cents == 0


def test_two_qualifying_debits_count_one_due_payment() -> None:
    txs = [_tx(-10_000, date(2026, 7, 29)), _tx(-10_000, date(2026, 7, 30))]

    status = loan_status(_loan(), txs, today=date(2026, 8, 1))

    assert status.paid_since_statement_cents == 10_000


def test_final_payment_counts_only_the_scheduled_remainder() -> None:
    txs = [_tx(-10_000, date(2026, month, 30)) for month in (7, 8, 9)]

    status = loan_status(_loan(balance_cents=25_000), txs, today=date(2026, 10, 1))

    assert status.paid_since_statement_cents == 25_000


def test_ordinary_loan_counts_two_payments_after_the_statement() -> None:
    txs = [
        _tx(-100_000, date(2026, 6, 15)),
        _tx(-100_000, date(2026, 6, 30)),
        _tx(-100_000, date(2026, 7, 30)),
        _tx(-100_000, date(2026, 8, 30)),
        _tx(100_000, date(2026, 7, 30)),
    ]

    status = loan_status(_loan(100_000, 500_000), txs, today=date(2026, 9, 23))

    assert status.paid_since_statement_cents == 200_000
