"""Tests for debts.store.remaining_cents (SPEC §9 section 3): one "amount
remaining" figure for both installments and loans, shared by /debts and the
dashboard.
"""

from datetime import date

from sonar.debts.model import Installment, InstallmentStatus, Loan, LoanStatus, MatchRule
from sonar.debts.store import DebtView, remaining_cents


def _installment_view(remaining: int) -> DebtView:
    debt = Installment(
        name="Sofa",
        total_cents=120_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=12,
        match=MatchRule("counterparty", "Furniture Store"),
    )
    status = InstallmentStatus(
        paid_cents=120_000 - remaining,
        remaining_cents=remaining,
        payments_made=3,
        payments_remaining=9,
        end_date=date(2026, 12, 5),
        paid_off=remaining == 0,
    )
    return DebtView(id=1, debt=debt, status=status, linked_payments=())


def _loan_view(projected: int, *, paid_off: bool) -> DebtView:
    debt = Loan(
        name="Car",
        balance_cents=500_000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100_000,
        interest_bp=None,
        match=MatchRule("mandate", "M-1"),
    )
    status = LoanStatus(
        projected_balance_cents=projected,
        payoff_date=None if not paid_off else date(2026, 8, 30),
        paid_since_statement_cents=200_000,
        paid_off=paid_off,
    )
    return DebtView(id=2, debt=debt, status=status, linked_payments=())


def test_remaining_cents_of_an_installment_is_its_remaining_cents() -> None:
    assert remaining_cents(_installment_view(90_000)) == 90_000


def test_remaining_cents_of_a_loan_is_its_projected_balance_cents() -> None:
    assert remaining_cents(_loan_view(300_000, paid_off=False)) == 300_000


def test_remaining_cents_of_a_paid_off_loan_is_zero() -> None:
    assert remaining_cents(_loan_view(0, paid_off=True)) == 0
