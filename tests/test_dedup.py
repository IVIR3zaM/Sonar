"""Tests for transaction fingerprints and per-file occurrence numbering."""

from dataclasses import replace
from datetime import date

from sonar.dedup import fingerprint, number_occurrences
from sonar.transactions import ParsedTransaction


def _tx(**overrides: object) -> ParsedTransaction:
    base = ParsedTransaction(
        account="DE00 1234",
        booking_date=date(2024, 3, 1),
        value_date=date(2024, 3, 1),
        amount_cents=-1299,
        currency="EUR",
        counterparty="Example Bakery",
        purpose="Card payment 0815",
        raw_row="raw",
    )
    return replace(base, **overrides)


def test_fingerprint_is_a_sha256_hex_digest() -> None:
    fp = fingerprint(_tx())

    assert len(fp) == 64
    int(fp, 16)


def test_case_and_whitespace_variants_share_a_fingerprint() -> None:
    plain = _tx()
    variant = _tx(
        account="  de00   1234 ",
        counterparty="EXAMPLE   bakery ",
        purpose="\tcard  PAYMENT\n0815",
    )

    assert fingerprint(plain) == fingerprint(variant)


def test_fields_outside_the_fingerprint_do_not_change_it() -> None:
    # Raw row and value date vary between export flavours of the same booking.
    assert fingerprint(_tx()) == fingerprint(_tx(raw_row="other", value_date=date(2024, 3, 2)))


def test_each_fingerprinted_field_changes_the_fingerprint() -> None:
    original = fingerprint(_tx())

    assert fingerprint(_tx(account="DE00 9999")) != original
    assert fingerprint(_tx(booking_date=date(2024, 3, 2))) != original
    assert fingerprint(_tx(amount_cents=-1300)) != original
    assert fingerprint(_tx(counterparty="Other Shop")) != original
    assert fingerprint(_tx(purpose="Card payment 0816")) != original


def test_text_shifted_between_counterparty_and_purpose_does_not_collide() -> None:
    left = _tx(counterparty="ab", purpose="c")
    right = _tx(counterparty="a", purpose="bc")

    assert fingerprint(left) != fingerprint(right)


def test_two_identical_rows_get_occurrences_one_and_two() -> None:
    first, second = _tx(), _tx()

    numbered = number_occurrences([first, second])

    assert [(tx, occ) for tx, _, occ in numbered] == [(first, 1), (second, 2)]
    assert numbered[0][1] == numbered[1][1] == fingerprint(first)


def test_occurrences_count_per_fingerprint_independently() -> None:
    bakery, shop = _tx(), _tx(counterparty="Other Shop")

    numbered = number_occurrences([bakery, shop, bakery])

    assert [occ for _, _, occ in numbered] == [1, 1, 2]


def test_row_order_does_not_change_the_fingerprint_occurrence_set() -> None:
    txs = [_tx(), _tx(counterparty="Other Shop"), _tx(), _tx(amount_cents=500), _tx()]

    forward = {(fp, occ) for _, fp, occ in number_occurrences(txs)}
    backward = {(fp, occ) for _, fp, occ in number_occurrences(list(reversed(txs)))}

    assert forward == backward
    assert len(forward) == len(txs)


def test_empty_input_numbers_nothing() -> None:
    assert number_occurrences([]) == []
