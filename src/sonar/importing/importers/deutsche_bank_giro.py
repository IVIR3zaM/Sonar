"""Deutsche Bank Girokonto (current account) CSV importer.

Confirmed layout, derived from the real export in `samples/` (not the German
locale SPEC §4 expected):

- UTF-8 with a BOM, LF line endings, `;` separator, `"` quoting.
- Dates are `M/D/YYYY`, unpadded. Amounts are English style with a thousands
  comma, e.g. `-2,167.12`.
- Preamble (7 lines before the header):
    L1 `Transactions`
    L2 `Account;Branch/Account number;IBAN;Currency`
    L3 `<account type>;<branch/account number>;<IBAN>;EUR` -- the account
       identifier is field 2 (the branch/account number), not field 1,
       which just names the account type (e.g. "AktivKonto").
    L4 blank
    L5 `M/D/YYYY - M/D/YYYY`
    L6 `Old balance;;;;<amt>;EUR` -- ignored; only the closing balance below
       is stored (SPEC §4 "current balance").
    L7 a note that pending transactions are not included.
- L8 header (18 columns): Booking date;Value date;Transaction Type;
  Beneficiary / Originator;Payment Details;IBAN / Account Number;BIC;
  Customer Reference;Mandate Reference;Creditor ID;Compensation amount;
  Original Amount;Ultimate creditor;Number of transactions;Number of
  cheques;Debit;Credit;Currency
- One data row per transaction. The amount is whichever of Debit/Credit is
  populated; the other is empty. Debit values are negative; Credit values
  are assumed positive (no negative Credit seen in the sample).
- Footer: `Account balance;<date>;;;<amt>;EUR`.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal

from sonar.transactions import ParsedBalance, ParsedTransaction

NAME = "Deutsche Bank Girokonto CSV"

_HEADER = [
    "Booking date",
    "Value date",
    "Transaction Type",
    "Beneficiary / Originator",
    "Payment Details",
    "IBAN / Account Number",
    "BIC",
    "Customer Reference",
    "Mandate Reference",
    "Creditor ID",
    "Compensation amount",
    "Original Amount",
    "Ultimate creditor",
    "Number of transactions",
    "Number of cheques",
    "Debit",
    "Credit",
    "Currency",
]

_ACCOUNT_LINE = 2  # 0-indexed: preamble L3
_IBAN_COL, _CUSTOMER_REF_COL = 5, 7
_MANDATE_REF_COL, _CREDITOR_ID_COL = 8, 9
_DEBIT_COL, _CREDIT_COL, _CURRENCY_COL = 15, 16, 17


def detect(content: bytes) -> bool:
    return _header_index(_decoded_lines(content)) is not None


def parse(content: bytes) -> list[ParsedTransaction]:
    lines = _decoded_lines(content)
    header_index = _header_index(lines)
    if header_index is None:
        return []

    account = _account(lines)
    transactions = []
    for line in lines[header_index + 1 :]:
        fields = _split(line)
        if len(fields) != len(_HEADER):
            continue  # the footer and any stray lines don't match the header width
        transactions.append(_parse_row(account, fields, raw_row=line))
    return transactions


def parse_balance(content: bytes) -> ParsedBalance | None:
    lines = _decoded_lines(content)
    account = _account(lines)
    for line in reversed(lines):
        fields = _split(line)
        if fields and fields[0] == "Account balance":
            return ParsedBalance(
                account=account,
                as_of=_parse_date(fields[1]),
                amount_cents=_parse_amount(fields[4]),
            )
    return None


def _parse_row(account: str, fields: list[str], raw_row: str) -> ParsedTransaction:
    debit, credit = fields[_DEBIT_COL], fields[_CREDIT_COL]
    return ParsedTransaction(
        account=account,
        booking_date=_parse_date(fields[0]),
        value_date=_parse_date(fields[1]),
        amount_cents=_parse_amount(debit or credit),
        currency=fields[_CURRENCY_COL],
        counterparty=fields[3],
        purpose=fields[4],
        raw_row=raw_row,
        iban=fields[_IBAN_COL] or None,
        mandate_ref=fields[_MANDATE_REF_COL] or None,
        creditor_id=fields[_CREDITOR_ID_COL] or None,
    )


def _account(lines: list[str]) -> str:
    return _split(lines[_ACCOUNT_LINE])[1]


def _header_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if _split(line) == _HEADER:
            return index
    return None


def _decoded_lines(content: bytes) -> list[str]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return []
    return text.splitlines()


def _split(line: str) -> list[str]:
    # A single-line csv.reader correctly keeps a quoted field's ';' intact.
    return next(csv.reader([line], delimiter=";", quotechar='"'), [])


def _parse_date(text: str) -> date:
    return datetime.strptime(text, "%m/%d/%Y").date()


def _parse_amount(text: str) -> int:
    # Amounts have exactly two decimals, so the *100 shift is always exact.
    return int(Decimal(text.replace(",", "")) * 100)
