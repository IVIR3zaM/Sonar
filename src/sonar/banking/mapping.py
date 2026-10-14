"""Enable Banking payloads as import rows (SPEC §13 Bank sync): pure, no clock, no storage.

Booked transactions become `ParsedTransaction`s and the balance list one `ParsedBalance`,
so the bank sync goes through the same import pipeline as a CSV upload.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from sonar.transactions import ParsedBalance, ParsedTransaction

SOURCE = "Deutsche Bank Girokonto API"
# The bank's available balance first; a closing or interim booked one only when it is missing.
_BALANCE_PREFERENCE = ("ITAV", "CLBD", "ITBD")


def transactions(payload: list[dict], account: str) -> list[ParsedTransaction]:
    """The booked transactions in `payload`, on `account`; ValueError when one is unreadable."""
    return [_transaction(tx, account) for tx in payload]


def sync_account(stored_csv_account: str | None, payload: list[dict]) -> str | None:
    """The account synced rows go on: the CSV's, so both sources match, else the own IBAN."""
    if stored_csv_account:
        return stored_csv_account
    for tx in payload:
        if iban := _own_iban(tx):
            return iban
    return None


def balance(balances: list[dict], account: str, as_of: date) -> ParsedBalance | None:
    """The preferred listed balance as of the sync date; None when the bank lists none."""
    if not balances:
        return None
    by_type = {entry.get("balance_type"): entry for entry in balances}
    chosen = next((by_type[t] for t in _BALANCE_PREFERENCE if t in by_type), balances[0])
    try:
        amount_cents = _cents(chosen["balance_amount"]["amount"])
    except (KeyError, TypeError):
        raise ValueError("The bank balance lacks an amount") from None
    return ParsedBalance(account=account, as_of=as_of, amount_cents=amount_cents)


def _transaction(tx: dict, account: str) -> ParsedTransaction:
    try:
        is_debit = tx["credit_debit_indicator"] == "DBIT"
        other = "creditor" if is_debit else "debtor"
        booking_date = date.fromisoformat(tx["booking_date"])
        value_date = date.fromisoformat(tx["value_date"]) if tx.get("value_date") else booking_date
        amount_cents = _cents(tx["transaction_amount"]["amount"])
        return ParsedTransaction(
            account=account,
            booking_date=booking_date,
            value_date=value_date,
            amount_cents=-abs(amount_cents) if is_debit else abs(amount_cents),
            currency=tx["transaction_amount"].get("currency") or "EUR",
            counterparty=(tx.get(other) or {}).get("name") or "",
            purpose=" ".join(tx.get("remittance_information") or []),
            raw_row=json.dumps(tx, sort_keys=True, ensure_ascii=False),
            iban=_iban(tx.get(f"{other}_account")),
            entry_reference=tx.get("entry_reference"),
        )
    except (KeyError, TypeError, AttributeError):
        raise ValueError("A bank transaction lacks a required field") from None


def _own_iban(tx: dict) -> str | None:
    own = "debtor_account" if tx.get("credit_debit_indicator") == "DBIT" else "creditor_account"
    return _iban(tx.get(own))


def _iban(account: dict | None) -> str | None:
    iban = (account or {}).get("iban")
    return iban.replace(" ", "") if iban else None


def _cents(amount: str) -> int:
    """Exact integer cents of a decimal string; never through float."""
    try:
        cents = Decimal(amount) * 100
    except (InvalidOperation, TypeError):
        raise ValueError(f"Not an amount: {amount!r}") from None
    if not cents.is_finite() or cents != cents.to_integral_value():
        raise ValueError(f"Amount finer than a cent: {amount!r}")
    return int(cents)
