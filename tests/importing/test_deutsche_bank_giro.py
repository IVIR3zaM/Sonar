"""Tests for the Deutsche Bank Girokonto CSV importer (SPEC §4)."""

from datetime import date
from pathlib import Path

from sonar.importing.importers import IMPORTERS, deutsche_bank_giro
from sonar.transactions import ParsedBalance

FIXTURE = Path(__file__).parent.parent / "fixtures" / "db_girokonto.csv"


def _content() -> bytes:
    return FIXTURE.read_bytes()


def test_detect_matches_the_fixture() -> None:
    assert deutsche_bank_giro.detect(_content()) is True


def test_detect_rejects_a_non_matching_csv() -> None:
    other = b"Date,Description,Amount\n2024-01-01,Coffee,-350\n"
    assert deutsche_bank_giro.detect(other) is False


def test_parse_returns_every_data_row_with_exact_values() -> None:
    txs = deutsche_bank_giro.parse(_content())

    assert len(txs) == 7

    first = txs[0]
    assert first.account == "123 4567890 01"
    assert first.booking_date == date(2026, 9, 23)
    assert first.value_date == date(2026, 9, 23)
    assert first.amount_cents == -216712
    assert first.currency == "EUR"
    assert first.counterparty == "Max Mustermann"
    assert first.purpose == "Salary payment; ref: ABC123"
    assert first.iban == "DE89123456789012345678"
    assert first.mandate_ref == "MND123"
    assert first.creditor_id == "DE11ZZZ00000000001"
    # The quoted purpose field's ';' must survive the delimiter split intact.
    assert "Salary payment; ref: ABC123" in first.raw_row


def test_parse_handles_a_credit_row() -> None:
    txs = deutsche_bank_giro.parse(_content())
    credit = next(tx for tx in txs if tx.counterparty == "John Doe")

    assert credit.amount_cents == 123456
    assert credit.purpose == "Invoice payment"


def test_parse_leaves_empty_optional_fields_as_none() -> None:
    txs = deutsche_bank_giro.parse(_content())
    acme = next(tx for tx in txs if tx.counterparty == "ACME GmbH")

    assert acme.mandate_ref is None
    assert acme.creditor_id is None
    assert acme.amount_cents == -4550


def test_parse_keeps_genuinely_identical_rows() -> None:
    txs = deutsche_bank_giro.parse(_content())
    dinners = [tx for tx in txs if tx.counterparty == "Restaurant XYZ"]

    assert len(dinners) == 2
    assert dinners[0] == dinners[1]


def test_parse_balance_reads_the_closing_account_balance_footer() -> None:
    balance = deutsche_bank_giro.parse_balance(_content())

    assert balance == ParsedBalance(
        account="123 4567890 01",
        as_of=date(2026, 9, 23),
        amount_cents=-44843,
    )


def test_parse_balance_ignores_the_old_balance_preamble_line() -> None:
    # 1,234.56 is the "Old balance" preamble value; the footer must win.
    balance = deutsche_bank_giro.parse_balance(_content())

    assert balance is not None
    assert balance.amount_cents != 123456


def test_registered_in_importers() -> None:
    assert deutsche_bank_giro in IMPORTERS


def test_detect_rejects_non_utf8_bytes() -> None:
    # Replace a character in the fixture with a Windows-1252 byte not valid UTF-8.
    content = _content()
    # Replace one byte in a field (e.g., in "Max Mustermann") with b"\xe4" (ä in cp1252)
    modified = content.replace(b"Max Mustermann", b"M\xe4x Mustermann")
    assert deutsche_bank_giro.detect(modified) is False


def test_parse_balance_returns_none_without_footer() -> None:
    # Remove the "Account balance" footer line from the fixture.
    content = _content()
    lines = content.decode("utf-8-sig").splitlines()
    # Remove the last line (the footer)
    lines = lines[:-1]
    modified = "\n".join(lines).encode("utf-8-sig")
    assert deutsche_bank_giro.parse_balance(modified) is None


def test_parse_returns_empty_list_for_non_bank_csv() -> None:
    # A CSV with no matching header should return an empty list.
    non_bank = b"not,a,bank,export\n1,2,3,4\n"
    assert deutsche_bank_giro.parse(non_bank) == []
