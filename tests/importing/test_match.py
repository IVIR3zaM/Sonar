"""Tests for pairing incoming bookings with stored ones across CSV and bank sync (SPEC §13)."""

from dataclasses import replace
from datetime import date

from sonar.importing.match import pair
from sonar.transactions import ParsedTransaction


def _tx(**overrides: object) -> ParsedTransaction:
    base = ParsedTransaction(
        account="DE00 1234",
        booking_date=date(2026, 10, 1),
        value_date=date(2026, 10, 1),
        amount_cents=-1299,
        currency="EUR",
        counterparty="Example Bakery",
        purpose="Card payment 0815 Berlin",
        raw_row="raw",
    )
    return replace(base, **overrides)


def test_truncated_space_padded_incoming_purpose_pairs_with_the_longer_stored_one() -> None:
    stored = [_tx(purpose="Card payment 0815 Berlin Mitte")]
    incoming = [_tx(purpose="  Card   payment 0815 ")]

    assert pair(incoming, stored) == {0: 0}


def test_stored_purpose_that_is_a_prefix_of_the_incoming_one_pairs() -> None:
    stored = [_tx(purpose="Card payment")]
    incoming = [_tx(purpose="Card payment 0815 Berlin Mitte")]

    assert pair(incoming, stored) == {0: 0}


def test_case_and_whitespace_in_counterparty_and_purpose_are_ignored() -> None:
    stored = [_tx(counterparty="EXAMPLE  bakery", purpose="CARD PAYMENT\n0815 berlin")]
    incoming = [_tx(counterparty=" example Bakery ", purpose="card payment 0815")]

    assert pair(incoming, stored) == {0: 0}


def test_prefix_match_wins_over_order() -> None:
    stored = [_tx(purpose="Rent October"), _tx(purpose="Card payment 0815 Berlin")]
    incoming = [_tx(purpose="Card payment 0815")]

    assert pair(incoming, stored) == {0: 1}


def test_leftover_rows_pair_one_to_one_in_order() -> None:
    stored = [_tx(purpose="First text"), _tx(purpose="Second text")]
    incoming = [_tx(purpose="Other A"), _tx(purpose="Other B"), _tx(purpose="Other C")]

    assert pair(incoming, stored) == {0: 0, 1: 1}


def test_fallback_pairs_only_the_rows_the_prefix_step_left_free() -> None:
    stored = [_tx(purpose="Alpha"), _tx(purpose="Beta 1")]
    incoming = [_tx(purpose="Gamma"), _tx(purpose="Beta")]

    assert pair(incoming, stored) == {1: 1, 0: 0}


def test_identical_keys_pair_by_count() -> None:
    stored = [_tx(), _tx()]
    incoming = [_tx(), _tx(), _tx()]

    assert pair(incoming, stored) == {0: 0, 1: 1}


def test_no_pairing_across_amount_date_account_or_counterparty() -> None:
    stored = [_tx()]
    incoming = [
        _tx(amount_cents=-1300),
        _tx(booking_date=date(2026, 10, 2)),
        _tx(account="DE00 9999"),
        _tx(counterparty="Other Bakery"),
    ]

    assert pair(incoming, stored) == {}


def test_each_stored_row_pairs_at_most_once() -> None:
    stored = [_tx(purpose="Card payment 0815 Berlin")]
    incoming = [_tx(purpose="Card payment"), _tx(purpose="Card payment 0815")]

    assert pair(incoming, stored) == {0: 0}
