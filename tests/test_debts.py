from datetime import date

import pytest

from sonar.debts import (
    Installment,
    InstallmentStatus,
    Loan,
    MatchRule,
    installment_status,
    linked_keys,
    matches,
)
from sonar.transactions import ParsedTransaction


def _tx(
    amount_cents: int,
    booking_date: date = date(2026, 1, 5),
    counterparty: str = "Sofa Store",
    mandate_ref: str | None = None,
    creditor_id: str | None = None,
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
        creditor_id=creditor_id,
    )


# --- MatchRule -----------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("iban", "Sofa Store"),  # not a supported field
        ("counterparty", ""),  # blank value
        ("counterparty", "   "),  # whitespace-only value
        ("mandate", ""),
    ],
)
def test_match_rule_rejects_invalid_field_or_value(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        MatchRule(field, value)


def test_matches_counterparty_is_case_and_space_insensitive_substring() -> None:
    rule = MatchRule("counterparty", "sofa store")
    tx = _tx(-10000, counterparty="  SOFA   STORE GMBH  ")
    assert matches(tx, rule)


def test_matches_counterparty_credit_never_matches() -> None:
    rule = MatchRule("counterparty", "sofa store")
    tx = _tx(10000, counterparty="Sofa Store")
    assert not matches(tx, rule)


def test_matches_mandate_exact_match() -> None:
    rule = MatchRule("mandate", "M-1")
    tx = _tx(-10000, mandate_ref="M-1")
    assert matches(tx, rule)


def test_matches_mandate_none_does_not_match() -> None:
    rule = MatchRule("mandate", "M-1")
    tx = _tx(-10000, mandate_ref=None)
    assert not matches(tx, rule)


# --- Installment / Loan validation ---------------------------------------


def test_installment_rejects_blank_name() -> None:
    with pytest.raises(ValueError):
        Installment(
            name="",
            total_cents=120000,
            rate_cents=10000,
            interval_months=1,
            first_payment_date=date(2026, 1, 5),
            payments_count=12,
            match=MatchRule("counterparty", "Sofa Store"),
        )


def test_installment_rejects_total_not_positive() -> None:
    with pytest.raises(ValueError):
        Installment(
            name="Sofa",
            total_cents=0,
            rate_cents=10000,
            interval_months=1,
            first_payment_date=date(2026, 1, 5),
            payments_count=12,
            match=MatchRule("counterparty", "Sofa Store"),
        )


def test_installment_rejects_rate_not_positive() -> None:
    with pytest.raises(ValueError):
        Installment(
            name="Sofa",
            total_cents=120000,
            rate_cents=0,
            interval_months=1,
            first_payment_date=date(2026, 1, 5),
            payments_count=12,
            match=MatchRule("counterparty", "Sofa Store"),
        )


def test_installment_rejects_interval_below_one() -> None:
    with pytest.raises(ValueError):
        Installment(
            name="Sofa",
            total_cents=120000,
            rate_cents=10000,
            interval_months=0,
            first_payment_date=date(2026, 1, 5),
            payments_count=12,
            match=MatchRule("counterparty", "Sofa Store"),
        )


def test_installment_rejects_payments_count_below_one() -> None:
    with pytest.raises(ValueError):
        Installment(
            name="Sofa",
            total_cents=120000,
            rate_cents=10000,
            interval_months=1,
            first_payment_date=date(2026, 1, 5),
            payments_count=0,
            match=MatchRule("counterparty", "Sofa Store"),
        )


def test_loan_rejects_blank_name() -> None:
    with pytest.raises(ValueError):
        Loan(
            name="",
            balance_cents=500000,
            balance_as_of=date(2026, 6, 30),
            rate_cents=100000,
            interest_bp=None,
            match=MatchRule("mandate", "M-1"),
        )


def test_loan_rejects_balance_not_positive() -> None:
    with pytest.raises(ValueError):
        Loan(
            name="Car loan",
            balance_cents=0,
            balance_as_of=date(2026, 6, 30),
            rate_cents=100000,
            interest_bp=None,
            match=MatchRule("mandate", "M-1"),
        )


def test_loan_rejects_rate_not_positive() -> None:
    with pytest.raises(ValueError):
        Loan(
            name="Car loan",
            balance_cents=500000,
            balance_as_of=date(2026, 6, 30),
            rate_cents=0,
            interest_bp=None,
            match=MatchRule("mandate", "M-1"),
        )


def test_loan_rejects_interest_bp_not_positive_when_set() -> None:
    with pytest.raises(ValueError):
        Loan(
            name="Car loan",
            balance_cents=500000,
            balance_as_of=date(2026, 6, 30),
            rate_cents=100000,
            interest_bp=0,
            match=MatchRule("mandate", "M-1"),
        )


def test_loan_allows_interest_bp_none() -> None:
    loan = Loan(
        name="Car loan",
        balance_cents=500000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100000,
        interest_bp=None,
        match=MatchRule("mandate", "M-1"),
    )
    assert loan.interest_bp is None


# --- installment_status ---------------------------------------------------


def _installment(payments_count: int = 12) -> Installment:
    return Installment(
        name="Sofa",
        total_cents=120000,
        rate_cents=10000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=payments_count,
        match=MatchRule("counterparty", "Sofa Store"),
    )


def test_installment_status_excludes_a_debit_before_the_tolerance_window() -> None:
    inst = _installment()
    txs = [
        _tx(-10000, date(2025, 12, 1)),  # 35 days early: an earlier purchase, not this plan
        _tx(-10000, date(2026, 1, 5)),
        _tx(-10000, date(2026, 2, 5)),
        _tx(-10000, date(2026, 3, 5)),
    ]
    status = installment_status(inst, txs)
    assert status == InstallmentStatus(
        paid_cents=30000,
        remaining_cents=90000,
        payments_made=3,
        payments_remaining=9,
        end_date=date(2026, 12, 5),
        paid_off=False,
    )


def test_installment_status_debit_five_days_before_first_payment_counts() -> None:
    inst = _installment()
    txs = [_tx(-10000, date(2025, 12, 31))]  # 5 days before 2026-01-05
    status = installment_status(inst, txs)
    assert status.payments_made == 1
    assert status.paid_cents == 10000


def test_installment_status_purchase_before_tolerance_window_is_excluded() -> None:
    # SPEC: earlier purchases at the same shop are not installments.
    inst = _installment()
    txs = [_tx(-10000, date(2025, 11, 1))]
    status = installment_status(inst, txs)
    assert status.payments_made == 0
    assert status.paid_cents == 0


def test_installment_status_overpaid_caps_remaining_at_zero_and_is_paid_off() -> None:
    inst = _installment(payments_count=2)
    txs = [
        _tx(-100000, date(2026, 1, 5)),
        _tx(-100000, date(2026, 2, 5)),
    ]
    status = installment_status(inst, txs)
    assert status.remaining_cents == 0
    assert status.paid_off


def test_installment_status_count_reached_with_amount_left_is_paid_off() -> None:
    inst = _installment(payments_count=2)
    txs = [
        _tx(-1000, date(2026, 1, 5)),
        _tx(-1000, date(2026, 2, 5)),
    ]
    status = installment_status(inst, txs)
    assert status.paid_off
    assert status.payments_remaining == 0
    assert status.remaining_cents == 118000


def test_installment_status_no_matches() -> None:
    inst = _installment()
    status = installment_status(inst, [])
    assert status.paid_cents == 0
    assert status.payments_made == 0
    assert not status.paid_off


def test_installment_status_end_date() -> None:
    inst = _installment()
    status = installment_status(inst, [])
    assert status.end_date == date(2026, 12, 5)


# --- linked_keys -----------------------------------------------------------


def test_linked_keys_mandate_and_counterparty() -> None:
    mandate_debt = Loan(
        name="Car loan",
        balance_cents=500000,
        balance_as_of=date(2026, 6, 30),
        rate_cents=100000,
        interest_bp=None,
        match=MatchRule("mandate", "M-1"),
    )
    txs = [_tx(-10000, mandate_ref="M-1", creditor_id="CRED")]
    assert linked_keys(mandate_debt, txs) == frozenset({"mandate:CRED/M-1"})


def test_linked_keys_counterparty_name_match() -> None:
    inst = _installment()
    txs = [
        _tx(-10000, date(2026, 1, 5), counterparty="Sofa Store"),
        _tx(-10000, date(2026, 2, 5), counterparty="Sofa Store"),
    ]
    keys = linked_keys(inst, txs)
    assert keys == frozenset({"counterparty:sofa store"})


def test_linked_keys_no_matches_is_empty() -> None:
    inst = _installment()
    assert linked_keys(inst, []) == frozenset()
