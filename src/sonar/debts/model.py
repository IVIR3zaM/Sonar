"""Debt model: installments and loans, matched to real bank payments (SPEC §7).

One model with a `kind` (installment or loan) sharing a match rule that links
hand-entered debts to the transactions that pay them off. Pure functions only:
`today` and transaction lists are passed in.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta

from sonar.debts import amortization
from sonar.importing.dedup import normalize_text
from sonar.recurring import schedule
from sonar.recurring.detect import payment_key, series_keys
from sonar.recurring.schedule import SchedulePeriod
from sonar.transactions import ParsedTransaction

MATCH_FIELDS = frozenset({"counterparty", "mandate", "purpose"})


@dataclass(frozen=True)
class MatchRule:
    field: str
    value: str

    def __post_init__(self) -> None:
        if self.field not in MATCH_FIELDS:
            raise ValueError(f"field must be one of {sorted(MATCH_FIELDS)}, got {self.field!r}")
        if not self.value.strip():
            raise ValueError("value must not be blank")


def matches(tx: ParsedTransaction, rule: MatchRule) -> bool:
    """Whether `tx` is a payment for this debt: debits only, per SPEC §7."""
    if tx.amount_cents >= 0:
        return False
    if rule.field == "counterparty":
        return normalize_text(rule.value) in normalize_text(tx.counterparty)
    if rule.field == "purpose":
        return normalize_text(rule.value) in normalize_text(tx.purpose)
    # mandate: None never matches an exact ref, however it is spelled.
    return tx.mandate_ref == rule.value.strip()


@dataclass(frozen=True)
class Installment:
    name: str
    total_cents: int
    rate_cents: int
    interval_months: int
    first_payment_date: date
    payments_count: int
    match: MatchRule

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if self.total_cents <= 0:
            raise ValueError(f"total must be positive, got {self.total_cents}")
        if self.rate_cents <= 0:
            raise ValueError(f"rate must be positive, got {self.rate_cents}")
        if self.interval_months < 1:
            raise ValueError(f"interval must be at least 1 month, got {self.interval_months}")
        if self.payments_count < 1:
            raise ValueError(f"payments_count must be at least 1, got {self.payments_count}")


@dataclass(frozen=True)
class Loan:
    name: str
    balance_cents: int
    balance_as_of: date
    rate_cents: int
    interest_bp: int | None
    match: MatchRule

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if self.balance_cents <= 0:
            raise ValueError(f"balance must be positive, got {self.balance_cents}")
        if self.rate_cents <= 0:
            raise ValueError(f"rate must be positive, got {self.rate_cents}")
        if self.interest_bp is not None and self.interest_bp <= 0:
            raise ValueError(f"interest_bp must be positive when set, got {self.interest_bp}")


@dataclass(frozen=True)
class InstallmentStatus:
    paid_cents: int
    remaining_cents: int
    payments_made: int
    payments_remaining: int
    end_date: date
    paid_off: bool


def installment_status(inst: Installment, txs: Iterable[ParsedTransaction]) -> InstallmentStatus:
    # Purchases before the first payment (even at the same shop) are not
    # installments, but a payment a few days early for bank-processing
    # reasons still is, hence the tolerance window instead of an exact date.
    earliest = inst.first_payment_date - schedule.TOLERANCE
    matched = [tx for tx in txs if matches(tx, inst.match) and tx.booking_date >= earliest]
    paid_cents = sum(abs(tx.amount_cents) for tx in matched)
    payments_made = len(matched)
    remaining_cents = max(inst.total_cents - paid_cents, 0)
    paid_off = remaining_cents == 0 or payments_made >= inst.payments_count
    payments_remaining = 0 if paid_off else inst.payments_count - payments_made
    end_date = schedule.add_months(
        inst.first_payment_date,
        (inst.payments_count - 1) * inst.interval_months,
        inst.first_payment_date.day,
    )
    return InstallmentStatus(
        paid_cents=paid_cents,
        remaining_cents=remaining_cents,
        payments_made=payments_made,
        payments_remaining=payments_remaining,
        end_date=end_date,
        paid_off=paid_off,
    )


@dataclass(frozen=True)
class LoanStatus:
    projected_balance_cents: int
    payoff_date: date | None
    paid_since_statement_cents: int
    paid_off: bool


def loan_status(loan: Loan, txs: Iterable[ParsedTransaction], today: date) -> LoanStatus:
    """Project the statement balance forward to `today` (SPEC §7)."""
    payments = amortization.loan_schedule(
        loan.balance_cents, loan.balance_as_of, loan.rate_cents, loan.interest_bp
    )
    projected = amortization.balance_on(loan.balance_cents, payments, today)
    # A shared debit can cover several loans, so count only this loan's
    # scheduled amount once per due date, ignoring extra repayments.
    paid_since = _paid_scheduled_amount(
        payments, (tx for tx in txs if matches(tx, loan.match)), today
    )
    return LoanStatus(
        projected_balance_cents=projected,
        payoff_date=amortization.payoff_date(payments),
        paid_since_statement_cents=paid_since,
        paid_off=projected == 0,
    )


def _paid_scheduled_amount(
    payments: Iterable[amortization.LoanPayment],
    debits: Iterable[ParsedTransaction],
    today: date,
) -> int:
    remaining = list(debits)
    paid_cents = 0
    for payment in sorted(payments, key=lambda payment: payment.due_date):
        if payment.due_date > today:
            break
        candidates = (
            index
            for index, tx in enumerate(remaining)
            if abs(tx.booking_date - payment.due_date) <= schedule.TOLERANCE
            and abs(tx.amount_cents) >= payment.amount_cents
        )
        closest = min(
            candidates,
            key=lambda index: (
                abs(remaining[index].booking_date - payment.due_date),
                remaining[index].booking_date,
            ),
            default=None,
        )
        if closest is not None:
            paid_cents += payment.amount_cents
            remaining.pop(closest)
    return paid_cents


def debt_schedule(
    debt: Installment | Loan, status: InstallmentStatus | LoanStatus
) -> tuple[SchedulePeriod, ...]:
    """Fixed-cost periods for the M5 forecast; a paid-off debt drops out (SPEC §7)."""
    if status.paid_off:
        return ()
    if isinstance(debt, Installment):
        period = SchedulePeriod(
            debt.first_payment_date,
            status.end_date,
            debt.rate_cents,
            debt.interval_months,
            debt.first_payment_date.day,
        )
        remainder = debt.total_cents - (debt.payments_count - 1) * debt.rate_cents
        # A total the rates already cover leaves no real remainder to forecast,
        # so the plan's own rate is the best guess for the last payment.
        final_cents = remainder if remainder > 0 else debt.rate_cents
        return _with_final_payment(period, final_cents, debt.payments_count)
    period = SchedulePeriod(
        debt.balance_as_of + timedelta(days=1),
        status.payoff_date,
        debt.rate_cents,
        1,
        debt.balance_as_of.day,
    )
    if status.payoff_date is None:
        # Without a payoff there is no last payment to single out.
        return (period,)
    payments = amortization.loan_schedule(
        debt.balance_cents, debt.balance_as_of, debt.rate_cents, debt.interest_bp
    )
    return _with_final_payment(period, payments[-1].amount_cents, len(payments))


def _with_final_payment(
    period: SchedulePeriod, final_cents: int, payment_count: int
) -> tuple[SchedulePeriod, ...]:
    # The last payment of a debt is usually not the regular rate; forecasting
    # the full rate there would overstate fixed costs in the payoff month.
    if final_cents == period.amount_cents:
        return (period,)
    # Callers only pass bounded periods: a debt with a final payment has an end.
    assert period.until is not None
    final = SchedulePeriod(
        period.until, period.until, final_cents, period.interval_months, period.day
    )
    if payment_count == 1:
        # An empty leading period would end before it starts.
        return (final,)
    return (replace(period, until=period.until - timedelta(days=1)), final)


def last_payment_date(debt: Installment | Loan, txs: Iterable[ParsedTransaction]) -> date | None:
    """The most recent matching debit's booking date, or None without one.

    The dashboard (M5) needs this per debt to apply the same early/late
    payment tolerance that fixed_due already applies to detected payments.
    """
    dates = [tx.booking_date for tx in txs if matches(tx, debt.match)]
    return max(dates) if dates else None


def latest_category(
    debt: Installment | Loan, rows: Iterable[tuple[ParsedTransaction, str | None]]
) -> str | None:
    """Latest categorized matching debit, with same-date ties going to the later row."""
    latest_date = None
    category = None
    for tx, label in rows:
        if label is not None and matches(tx, debt.match):
            if latest_date is None or tx.booking_date >= latest_date:
                latest_date = tx.booking_date
                category = label
    return category


def linked_keys(debt: Installment | Loan, txs: Iterable[ParsedTransaction]) -> frozenset[str]:
    """Detection keys of every matching debit in the whole history.

    Detection groups the whole transaction history (SPEC §6), so a debt links
    to a recurring payment through the same key regardless of date range.
    """
    # Split keys (one per same-day charge) are what detection stores for a shared
    # mandate; the unsplit key is linked too so a payment kept under it stays linked.
    keyed = [
        (tx, key, payment_key(tx))
        for tx, key in series_keys(tx for tx in txs if tx.amount_cents < 0)
    ]
    keys = {k for tx, key, base in keyed if matches(tx, debt.match) for k in (key, base)}
    if debt.match.field == "purpose":
        # A creditor mandate groups other subscriptions under the same key, so a
        # key that also holds a debit this rule does not match is never linked.
        keys -= {k for tx, key, base in keyed if not matches(tx, debt.match) for k in (key, base)}
    return frozenset(keys)
