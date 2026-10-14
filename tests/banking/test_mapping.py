"""Tests for banking/mapping.py: Enable Banking payloads as import rows (SPEC §13 Bank sync)."""

import json
from datetime import date

import pytest

from sonar.banking import mapping

ACCOUNT = "DE00111122223333444455"
SYNC_DAY = date(2026, 10, 14)


def _debit(**overrides) -> dict:
    tx = {
        "entry_reference": "ref-1",
        "transaction_amount": {"currency": "EUR", "amount": "12.34"},
        "credit_debit_indicator": "DBIT",
        "creditor": {"name": "Grocer Example"},
        "creditor_account": {"iban": "DE99 0000 0000 0000 0000 01"},
        "debtor": {"name": "Owner Example"},
        "debtor_account": {"iban": "DE00 1111 2222 3333 4444 55"},
        "remittance_information": ["Card payment", "Store 42"],
        "booking_date": "2026-10-12",
        "value_date": "2026-10-11",
    }
    return tx | overrides


def _credit(**overrides) -> dict:
    tx = {
        "entry_reference": "ref-2",
        "transaction_amount": {"currency": "EUR", "amount": "2500.00"},
        "credit_debit_indicator": "CRDT",
        "creditor": {"name": "Owner Example"},
        "creditor_account": {"iban": "DE00111122223333444455"},
        "debtor": {"name": "Employer Example"},
        "debtor_account": {"iban": "DE88000000000000000002"},
        "remittance_information": ["Salary October"],
        "booking_date": "2026-10-01",
        "value_date": "2026-10-01",
    }
    return tx | overrides


def _one(tx: dict):
    (parsed,) = mapping.transactions([tx], ACCOUNT)
    return parsed


def test_a_debit_is_negative_exact_cents_with_the_creditor_as_counterparty():
    parsed = _one(_debit())

    assert parsed.amount_cents == -1234
    assert parsed.counterparty == "Grocer Example"
    assert parsed.entry_reference == "ref-1"


def test_a_credit_is_positive_with_the_debtor_as_counterparty():
    parsed = _one(_credit())

    assert parsed.amount_cents == 250000
    assert parsed.counterparty == "Employer Example"


def test_the_iban_is_the_other_sides_account_without_spaces():
    assert _one(_debit()).iban == "DE99000000000000000001"
    assert _one(_credit()).iban == "DE88000000000000000002"


def test_amounts_are_exact_cents_without_float_rounding():
    assert (
        _one(_debit(transaction_amount={"currency": "EUR", "amount": "0.29"})).amount_cents == -29
    )
    assert (
        _one(_credit(transaction_amount={"currency": "EUR", "amount": "1.1"})).amount_cents == 110
    )


def test_an_amount_finer_than_cents_is_refused():
    with pytest.raises(ValueError):
        _one(_debit(transaction_amount={"currency": "EUR", "amount": "1.005"}))


def test_purpose_joins_the_remittance_lines_with_a_space():
    assert _one(_debit()).purpose == "Card payment Store 42"
    assert _one(_debit(remittance_information=None)).purpose == ""


def test_value_date_falls_back_to_the_booking_date():
    parsed = _one(_debit(value_date=None))

    assert parsed.booking_date == date(2026, 10, 12)
    assert parsed.value_date == date(2026, 10, 12)
    assert _one(_debit()).value_date == date(2026, 10, 11)


def test_account_currency_and_unset_fields():
    parsed = _one(_debit())

    assert parsed.account == ACCOUNT
    assert parsed.currency == "EUR"
    assert parsed.mandate_ref is None
    assert parsed.creditor_id is None


def test_raw_row_is_the_payload_as_sorted_json():
    tx = _debit(creditor={"name": "Bäcker Example"})

    assert _one(tx).raw_row == json.dumps(tx, sort_keys=True, ensure_ascii=False)


def test_a_missing_counterparty_is_empty():
    assert _one(_debit(creditor=None)).counterparty == ""


def test_the_account_is_the_stored_csv_account_when_there_is_one():
    assert mapping.sync_account("DE00STOREDCSVACCOUNT", [_debit()]) == "DE00STOREDCSVACCOUNT"


def test_the_account_falls_back_to_the_own_side_iban_without_spaces():
    assert mapping.sync_account(None, [_debit()]) == "DE00111122223333444455"
    assert mapping.sync_account(None, [_credit()]) == "DE00111122223333444455"


def test_no_account_without_a_stored_row_or_an_own_iban():
    assert mapping.sync_account(None, []) is None


def _balance(kind: str, amount: str) -> dict:
    return {
        "name": kind,
        "balance_type": kind,
        "balance_amount": {"currency": "EUR", "amount": amount},
    }


def test_the_balance_prefers_itav_then_clbd_then_itbd():
    listed = [_balance("ITBD", "3.00"), _balance("CLBD", "2.00"), _balance("ITAV", "1.00")]

    assert mapping.balance(listed, ACCOUNT, SYNC_DAY).amount_cents == 100
    assert mapping.balance(listed[:2], ACCOUNT, SYNC_DAY).amount_cents == 200
    assert mapping.balance(listed[:1], ACCOUNT, SYNC_DAY).amount_cents == 300


def test_the_balance_falls_back_to_the_first_listed():
    listed = [_balance("XPCD", "-45.60"), _balance("OTHR", "9.00")]

    parsed = mapping.balance(listed, ACCOUNT, SYNC_DAY)

    assert parsed.amount_cents == -4560


def test_the_balance_is_as_of_the_sync_date_on_the_same_account():
    parsed = mapping.balance([_balance("ITAV", "1234.56")], ACCOUNT, SYNC_DAY)

    assert (parsed.account, parsed.as_of, parsed.amount_cents) == (ACCOUNT, SYNC_DAY, 123456)


def test_no_balance_when_none_is_listed():
    assert mapping.balance([], ACCOUNT, SYNC_DAY) is None
