from dataclasses import replace
from datetime import date

from sonar.recurring.detect import detect_recurring, payment_key, series_keys
from sonar.transactions import ParsedTransaction

IBAN = "DE00 1111 2222 3333 4444 55"


def _tx(month: int, day: int, amount: int, mandate: str | None = None) -> ParsedTransaction:
    return ParsedTransaction(
        account="test",
        booking_date=date(2026, month, day),
        value_date=date(2026, month, day),
        amount_cents=-amount,
        currency="EUR",
        counterparty="Example Utility",
        purpose="Debit",
        raw_row="",
        iban=IBAN if mandate else IBAN.replace(" ", "").lower(),
        mandate_ref=mandate,
        creditor_id="CREDITOR" if mandate else None,
    )


def test_synced_debits_continue_the_mandate_after_an_amount_change():
    txs = [_tx(month, 14, 1999, "MANDATE-A") for month in (5, 6, 7)]
    txs += [_tx(month, 14, 2199) for month in (8, 9)]

    [payment] = detect_recurring(
        [(tx, "Utilities") for tx in txs], {"Utilities": "fixed"}, date(2026, 9, 15)
    )

    assert payment.key == "mandate:CREDITOR/MANDATE-A"
    assert payment.last_paid_date == date(2026, 9, 14)
    assert payment.schedule.amount_cents == 2199


def test_shared_iban_chooses_amount_then_wrapped_day_before_ranking():
    charges = [("A", 14, 300), ("A", 14, 3000), ("B", 1, 1275), ("C", 2, 3900), ("D", 7, 4100)]
    mandate_rows = [
        _tx(month, day, amount, f"MANDATE-{key}")
        for month in (5, 6, 7)
        for key, day, amount in charges
    ]
    synced_rows = [_tx(8, day, amount) for _, day, amount in charges]
    synced_rows += [_tx(9, 2, 1350), _tx(10, 31, 1350)]

    pairs = series_keys(mandate_rows + synced_rows)

    assert [key for _, key in pairs[-7:]] == [
        "mandate:CREDITOR/MANDATE-A#2",
        "mandate:CREDITOR/MANDATE-A#1",
        "mandate:CREDITOR/MANDATE-B",
        "mandate:CREDITOR/MANDATE-C",
        "mandate:CREDITOR/MANDATE-D",
        "mandate:CREDITOR/MANDATE-C",
        "mandate:CREDITOR/MANDATE-B",
    ]


def test_only_counterparty_rows_with_a_known_iban_inherit():
    mandate = _tx(7, 14, 1999, "MANDATE-A")
    synced = _tx(8, 14, 1999)
    unchanged = [
        replace(synced, counterparty="Abrechnung Karte", purpose="Example Shop // card"),
        replace(synced, iban=None),
        replace(synced, iban="DE00 9999", counterparty="Other Utility"),
        replace(synced, creditor_id="CREDITOR"),
    ]

    assert [key for _, key in series_keys([mandate, *unchanged])][1:] == [
        payment_key(tx) for tx in unchanged
    ]
    assert [payment_key(tx).split(":")[0] for tx in unchanged] == [
        "card",
        "counterparty",
        "counterparty",
        "creditor",
    ]


def test_equal_candidates_choose_lowest_key_independent_of_input_order():
    a = _tx(7, 14, 1999, "MANDATE-A")
    b = _tx(7, 14, 1999, "MANDATE-B")
    synced = _tx(8, 14, 1999)

    assert series_keys([b, a, synced])[-1][1] == "mandate:CREDITOR/MANDATE-A"


def test_candidate_amount_comes_from_latest_mandate_rows_only():
    txs = [
        _tx(6, 14, 1999, "MANDATE-A"),
        _tx(7, 14, 2199, "MANDATE-A"),
        _tx(7, 2, 1999, "MANDATE-B"),
        _tx(8, 14, 1999),
        _tx(9, 14, 2199),
    ]

    assert [key for _, key in series_keys(txs)][-2:] == [
        "mandate:CREDITOR/MANDATE-B",
        "mandate:CREDITOR/MANDATE-A",
    ]
