"""Tests for the Consors Finanz Mastercard statement PDF importer (SPEC §4)."""

from datetime import date
from pathlib import Path

from sonar.importing.importers import consors_finanz_card, deutsche_bank_giro
from tests.importing.consors_pdf import CARD_LINE, Line, statement_pdf

DB_FIXTURE = Path(__file__).parent.parent / "fixtures" / "db_girokonto.csv"

COLUMNS = ("Umsatzdatum", "Buchungsdatum", "Verwendungszweck", "Soll/Haben in EUR")

SUMMARY_PAGE: list[Line] = [
    "Consors Finanz, Postfach 00 00 00, 00000 Musterstadt",
    "Ihr Verfügungsrahmen: 1.000,00 EUR",
    CARD_LINE,
    ("Saldo", "Rate", "Abbuchungsdatum"),
    ("Ratenzahlung", "1.058,48 EUR", "33,00 EUR", "01.09.2026"),
    ("Einmalzahlung vierteljährlich", "205,19.EUR", "01.10.2026"),
    "Aktuell offener Gesamtsaldo 1.263,67 EUR",
]

RATENZAHLUNG: list[Line] = [
    "Umsätze Ratenzahlung",
    COLUMNS,
    ("ALTER SALDO VOM 20.07.26", "", "", "-1.069,58"),
    ("03.07.26", "04.07.26", "MUSTER MÖBELHAUS", "-1.234,56"),
    ("", "20.07.26", "MONATLICHE ZINSEN*", "-4,95"),
    ("", "01.08.26", "EINGEGANGENE ZAHLUNG", "+433,88"),
    ("", "13.07.26", "UMB. EINMAL- AUF RATENZAHLUNG", "-311,90"),
    ("GESAMTUMSÄTZE", "", "", "-1.551,41"),
    ("", "", "", "+433,88"),
    ("NEUER SALDO VOM 20.08.26", "", "", "-1.058,48"),
    "* genauere Informationen finden Sie auf unserer Website",
]

EINMALZAHLUNG: list[Line] = [
    "Einmalzahlung vierteljährlich",
    COLUMNS,
    ("ALTER SALDO VOM 20.07.26", "", "", "-672,60"),
    ("21.12.25", "22.12.25", "BEISPIEL APOTHEKE", "-20,00"),
    ("", "23.07.26", "CASHCLICK UEBERWEISUNG AUF IHR GIROKONTO", "-50,00"),
    ("", "13.07.26", "UMB. EINMAL- AUF RATENZAHLUNG", "+311,90"),
    ("GESAMTUMSÄTZE", "", "", "-70,00"),
    ("", "", "", "+311,90"),
    "2 / 3",
]

LETTER_PAGE: list[Line] = [
    "Consors Finanz, Postfach 00 00 00, 00000 Musterstadt",
    "Duisburg, 22.07.2026",
    "Zinsanpassung für Ihren Kreditrahmen!",
    ("01.08.26", "AB DIESEM DATUM GILT", "-15,89"),
]


def _statement(*pages: list[Line]) -> bytes:
    return statement_pdf(list(pages))


def _full_statement() -> bytes:
    return _statement(SUMMARY_PAGE, RATENZAHLUNG + EINMALZAHLUNG, LETTER_PAGE)


def test_parse_reads_a_ratenzahlung_row_and_a_fee_row_without_umsatzdatum() -> None:
    rows: list[Line] = [
        "Umsätze Ratenzahlung",
        COLUMNS,
        ("03.07.26", "04.07.26", "MUSTER MÖBELHAUS", "-1.234,56"),
        ("", "20.07.26", "MONATLICHE ZINSEN*", "-4,95"),
        ("GESAMTUMSÄTZE", "", "", "-1.239,51"),
    ]
    txs = consors_finanz_card.parse(_statement(SUMMARY_PAGE, rows))

    assert len(txs) == 2
    purchase, fee = txs
    assert purchase.account == "Consors Mastercard 1234"
    assert purchase.value_date == date(2026, 7, 3)
    assert purchase.booking_date == date(2026, 7, 4)
    assert purchase.amount_cents == -123456
    assert purchase.counterparty == "MUSTER MÖBELHAUS"
    assert purchase.purpose == "Ratenzahlung"
    assert purchase.currency == "EUR"
    assert purchase.raw_row == "03.07.26 04.07.26 MUSTER MÖBELHAUS -1.234,56"
    assert fee.account == "Consors Mastercard 1234"
    assert fee.booking_date == date(2026, 7, 20)
    assert fee.value_date == date(2026, 7, 20)
    assert fee.amount_cents == -495
    assert fee.purpose == "Ratenzahlung"


def test_parse_reads_both_sections_with_their_purpose() -> None:
    txs = consors_finanz_card.parse(_full_statement())

    assert [(tx.counterparty, tx.purpose, tx.amount_cents) for tx in txs] == [
        ("MUSTER MÖBELHAUS", "Ratenzahlung", -123456),
        ("MONATLICHE ZINSEN*", "Ratenzahlung", -495),
        ("EINGEGANGENE ZAHLUNG", "Ratenzahlung", 43388),
        ("BEISPIEL APOTHEKE", "Einmalzahlung", -2000),
        ("CASHCLICK UEBERWEISUNG AUF IHR GIROKONTO", "Einmalzahlung", -5000),
    ]
    assert {tx.account for tx in txs} == {"Consors Mastercard 1234"}


def test_parse_maps_two_digit_years_into_the_2000s() -> None:
    txs = consors_finanz_card.parse(_full_statement())
    pharmacy = next(tx for tx in txs if tx.counterparty == "BEISPIEL APOTHEKE")

    assert pharmacy.value_date == date(2025, 12, 21)
    assert pharmacy.booking_date == date(2025, 12, 22)


def test_parse_drops_the_umbuchung_pair_between_sections() -> None:
    txs = consors_finanz_card.parse(_full_statement())

    assert not any(tx.counterparty.startswith("UMB.") for tx in txs)


def test_parse_skips_saldo_totals_bare_amounts_and_the_letter_page() -> None:
    txs = consors_finanz_card.parse(_full_statement())

    assert len(txs) == 5
    assert not any("SALDO" in tx.raw_row or "GESAMT" in tx.raw_row for tx in txs)
    assert not any(tx.counterparty == "AB DIESEM DATUM GILT" for tx in txs)


def test_detect_matches_the_synthetic_statement() -> None:
    assert consors_finanz_card.detect(_full_statement()) is True


def test_detect_rejects_the_deutsche_bank_csv() -> None:
    assert consors_finanz_card.detect(DB_FIXTURE.read_bytes()) is False


def test_detect_rejects_a_non_pdf() -> None:
    assert consors_finanz_card.detect(b"Consors Finanz Mastercard 0000 XXXX XXXX 1234") is False


def test_detect_rejects_a_pdf_without_the_consors_phrases() -> None:
    assert consors_finanz_card.detect(_statement(["Some other bank", "Kontoauszug"])) is False


def test_detect_rejects_a_pdf_without_the_card_number() -> None:
    page: list[Line] = [
        "Consors Finanz, Postfach 00 00 00",
        "Kontoauszug zu Consors Finanz Mastercard® Nr.:",
    ]
    assert consors_finanz_card.detect(_statement(page)) is False


def test_detect_rejects_truncated_pdf_bytes() -> None:
    assert consors_finanz_card.detect(_full_statement()[:200]) is False


def test_deutsche_bank_detect_rejects_the_statement_pdf() -> None:
    assert deutsche_bank_giro.detect(_full_statement()) is False
