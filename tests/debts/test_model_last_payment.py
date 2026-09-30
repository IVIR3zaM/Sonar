"""Tests for debts.model.last_payment_date (SPEC §7): the latest matching debit."""

from datetime import date

from sonar.debts.model import Installment, MatchRule, last_payment_date
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


def _installment(match: MatchRule) -> Installment:
    return Installment(
        name="Sofa",
        total_cents=120_000,
        rate_cents=10_000,
        interval_months=1,
        first_payment_date=date(2026, 1, 5),
        payments_count=12,
        match=match,
    )


def test_last_payment_date_is_the_latest_of_several_matches() -> None:
    debt = _installment(MatchRule("counterparty", "Sofa Store"))
    txs = [
        _tx(-10_000, date(2026, 1, 5)),
        _tx(-10_000, date(2026, 3, 5)),
        _tx(-10_000, date(2026, 2, 5)),
    ]
    assert last_payment_date(debt, txs) == date(2026, 3, 5)


def test_last_payment_date_ignores_credits_and_non_matching_debits() -> None:
    debt = _installment(MatchRule("counterparty", "Sofa Store"))
    txs = [
        _tx(10_000, date(2026, 3, 5)),  # a credit never matches
        _tx(-5_000, date(2026, 2, 1), counterparty="Other Shop"),  # non-matching counterparty
        _tx(-10_000, date(2026, 1, 5)),  # the only real match
    ]
    assert last_payment_date(debt, txs) == date(2026, 1, 5)


def test_last_payment_date_is_none_without_a_match() -> None:
    debt = _installment(MatchRule("counterparty", "Sofa Store"))
    txs = [
        _tx(10_000, date(2026, 3, 5)),
        _tx(-5_000, date(2026, 2, 1), counterparty="Other Shop"),
    ]
    assert last_payment_date(debt, txs) is None
