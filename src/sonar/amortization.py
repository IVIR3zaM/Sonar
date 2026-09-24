"""Loan projection from a statement balance (SPEC §7).

A loan is entered as a balance on a statement date plus a monthly rate. Payments
fall monthly on the statement's day of month, starting the month after it.
Integer cents only, so interest is rounded to a whole cent every month the way
a bank statement shows it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sonar.schedule import add_months

# A rate at or below the monthly interest never pays the loan off, so the
# projection needs a hard end; 50 years is longer than any household loan.
MAX_MONTHS = 600

# Annual basis points over 12 months: bp / 10_000 / 12 = bp / 120_000.
_MONTHLY_BP_DIVISOR = 120_000


@dataclass(frozen=True)
class LoanPayment:
    due_date: date
    amount_cents: int
    balance_after_cents: int


def loan_schedule(
    balance_cents: int, as_of: date, rate_cents: int, interest_bp: int | None
) -> list[LoanPayment]:
    """Monthly payments from the statement balance until it reaches 0."""
    schedule: list[LoanPayment] = []
    balance = balance_cents
    for n in range(1, MAX_MONTHS + 1):
        if balance <= 0:
            break
        # Counted from the anchor, not the previous due date, so day 31 comes
        # back after a short month instead of drifting to the 28th for good.
        due = add_months(as_of, n, as_of.day)
        owed = balance + _monthly_interest(balance, interest_bp)
        payment = min(rate_cents, owed)
        balance = owed - payment
        schedule.append(LoanPayment(due, payment, balance))
    return schedule


def balance_on(start_balance_cents: int, schedule: list[LoanPayment], on: date) -> int:
    """Balance after the last payment due on or before `on`."""
    balance = start_balance_cents
    for payment in schedule:
        if payment.due_date > on:
            break
        balance = payment.balance_after_cents
    return balance


def payoff_date(schedule: list[LoanPayment]) -> date | None:
    """Date of the final payment, or None when the projection never reaches 0."""
    if schedule and schedule[-1].balance_after_cents == 0:
        return schedule[-1].due_date
    return None


def _monthly_interest(balance_cents: int, interest_bp: int | None) -> int:
    # No interest rate means a linear loan (SPEC §7).
    if interest_bp is None:
        return 0
    # Adding half the divisor before floor division rounds half a cent up.
    return (balance_cents * interest_bp + _MONTHLY_BP_DIVISOR // 2) // _MONTHLY_BP_DIVISOR
