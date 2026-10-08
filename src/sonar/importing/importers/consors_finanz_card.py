"""Consors Finanz Mastercard monthly statement PDF importer.

Confirmed layout, derived from the real statements in `samples/consors/` and
read with pypdf's layout text extraction, runs of spaces collapsed:

- Page 1 is a summary: address block, credit limit, the line
  `Kontoauszug zu Consors Finanz Mastercard® Nr.: NNNN XXXX XXXX NNNN` (the
  masked card number; its last four digits name the source), and a table of
  the open balance per repayment kind. It holds no transactions.
- The transactions follow in up to two sections, each opened by its title
  line and then the column header
  `Umsatzdatum Buchungsdatum Verwendungszweck Soll/Haben in EUR`:
    `Umsätze Ratenzahlung`          -- the instalment balance
    `Einmalzahlung vierteljährlich` -- the pay-in-full balance
  A section ends at its `GESAMTUMSÄTZE <debits>` line, followed by a bare
  `<credits>` line when there were credits, then `NEUER SALDO VOM dd.mm.yy`
  (missing when the page runs out). Sections start on a new page or follow
  each other on one page.
- A row is `[Umsatzdatum] Buchungsdatum Verwendungszweck ±1.234,56`; dates
  are `dd.mm.yy`. Fees, interest (`MONATLICHE ZINSEN*`), insurance and
  payments in (`EINGEGANGENE ZAHLUNG`) have no Umsatzdatum.
- `ALTER SALDO VOM`, totals, footers, footnotes and page numbers never match
  the row shape. A trailing letter page (e.g. an interest-rate notice) comes
  after the last section and is ignored.
- `UMB. EINMAL- AUF RATENZAHLUNG` moves a balance from one section to the
  other as a -/+ pair; it is internal to the card account and is dropped.
- There is no IBAN, mandate or creditor id per row, and no closing balance
  is imported (no `parse_balance`).
"""

from __future__ import annotations

import io
import re
from datetime import date

from pypdf import PdfReader

from sonar.transactions import ParsedTransaction

NAME = "Consors Finanz Mastercard PDF"

_PDF_MAGIC = b"%PDF-"
_ISSUER = "Consors Finanz"
_STATEMENT_TITLE = "Kontoauszug zu Consors Finanz Mastercard"
_CARD_NUMBER = re.compile(r"\d{4} XXXX XXXX (\d{4})")

_SECTION_PURPOSES = {
    "Umsätze Ratenzahlung": "Ratenzahlung",
    "Einmalzahlung vierteljährlich": "Einmalzahlung",
}
_COLUMN_HEADER = "Umsatzdatum Buchungsdatum Verwendungszweck"
_SECTION_END = "GESAMTUMSÄTZE"
_SECTION_TRANSFER = "UMB. EINMAL- AUF RATENZAHLUNG"

_DATE = r"\d{2}\.\d{2}\.\d{2}"
_ROW = re.compile(
    rf"^(?P<first>{_DATE}) (?:(?P<second>{_DATE}) )?(?P<text>.+) "
    r"(?P<amount>[+-]\d{1,3}(?:\.\d{3})*,\d{2})$"
)


def detect(content: bytes) -> bool:
    if not content.startswith(_PDF_MAGIC):
        return False
    try:
        text = "\n".join(_lines(content))
    except Exception:  # pypdf raises many error types on malformed or truncated PDFs
        return False
    return _ISSUER in text and _STATEMENT_TITLE in text and _card_digits(text) is not None


def parse(content: bytes) -> list[ParsedTransaction]:
    lines = _lines(content)
    account = f"Consors Mastercard {_card_digits('\n'.join(lines))}"
    transactions: list[ParsedTransaction] = []
    for purpose, line in _section_rows(lines):
        match = _ROW.match(line)
        if match is None or match["text"].startswith(_SECTION_TRANSFER):
            continue
        transactions.append(_parse_row(account, purpose, match, raw_row=line))
    return transactions


def _section_rows(lines: list[str]) -> list[tuple[str, str]]:
    """Each line inside a section's table, paired with that section's purpose."""
    rows = []
    purpose, in_table = None, False
    for line in lines:
        if line in _SECTION_PURPOSES:
            purpose, in_table = _SECTION_PURPOSES[line], False
        elif line.startswith(_COLUMN_HEADER):
            in_table = purpose is not None
        elif line.startswith(_SECTION_END):
            purpose, in_table = None, False
        elif in_table and purpose is not None:
            rows.append((purpose, line))
    return rows


def _parse_row(account: str, purpose: str, match: re.Match[str], raw_row: str) -> ParsedTransaction:
    booking_date = _parse_date(match["second"] or match["first"])
    value_date = _parse_date(match["first"])
    return ParsedTransaction(
        account=account,
        booking_date=booking_date,
        value_date=value_date,
        amount_cents=_parse_amount(match["amount"]),
        currency="EUR",
        counterparty=match["text"],
        purpose=purpose,
        raw_row=raw_row,
    )


def _lines(content: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(content))
    lines = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout")
        lines.extend(_collapse_spaces(line) for line in text.splitlines())
    return [line for line in lines if line]


def _collapse_spaces(line: str) -> str:
    # Layout extraction pads columns with runs of spaces.
    return " ".join(line.split())


def _card_digits(text: str) -> str | None:
    match = _CARD_NUMBER.search(text)
    return match[1] if match else None


def _parse_date(text: str) -> date:
    day, month, year = (int(part) for part in text.split("."))
    return date(2000 + year, month, day)


def _parse_amount(text: str) -> int:
    sign = -1 if text.startswith("-") else 1
    euros, cents = text[1:].replace(".", "").split(",")
    return sign * (int(euros) * 100 + int(cents))
