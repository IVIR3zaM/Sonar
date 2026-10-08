"""Importing Consors card statement PDFs through the store (SPEC §4, incl. Idempotency)."""

import sqlite3

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.importing.store import import_file
from tests.importing.consors_pdf import CARD_LINE, Line, statement_pdf

COLUMNS = ("Umsatzdatum", "Buchungsdatum", "Verwendungszweck", "Soll/Haben in EUR")
SOURCE = "Consors Finanz Mastercard PDF"
CARD_LABEL = "Consors Mastercard 1234"

SHOP = ("03.07.26", "04.07.26", "MUSTER MÖBELHAUS", "-1.234,56")
FEE = ("", "20.07.26", "MONATLICHE ZINSEN*", "-4,95")
PAYMENT = ("", "01.08.26", "EINGEGANGENE ZAHLUNG", "+433,88")
PHARMACY = ("21.12.25", "22.12.25", "BEISPIEL APOTHEKE", "-20,00")
CASHCLICK = ("", "23.07.26", "CASHCLICK UEBERWEISUNG AUF IHR GIROKONTO", "-50,00")

Row = tuple[str, str, str, str]


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _statement(ratenzahlung: list[Row], einmalzahlung: list[Row] | None = None) -> bytes:
    page: list[Line] = [CARD_LINE, "Umsätze Ratenzahlung", COLUMNS, *ratenzahlung]
    page.append(("GESAMTUMSÄTZE", "", "", "-1,00"))
    if einmalzahlung is not None:
        page += ["Einmalzahlung vierteljährlich", COLUMNS, *einmalzahlung]
        page.append(("GESAMTUMSÄTZE", "", "", "-1,00"))
    return statement_pdf([page])


def _count(conn: sqlite3.Connection, table: str = "transactions") -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_first_import_adds_every_row_and_stores_no_balance(conn) -> None:
    content = _statement([SHOP, FEE, PAYMENT], [PHARMACY, CASHCLICK])

    result = import_file(conn, content, "card.pdf")

    assert result.format == SOURCE
    assert result.added == 5
    assert result.duplicates == 0
    assert _count(conn) == 5
    assert _count(conn, "balances") == 0


def test_same_file_imported_twice_adds_nothing_the_second_time(conn) -> None:
    content = _statement([SHOP, FEE], [PHARMACY])
    import_file(conn, content, "card.pdf")

    second = import_file(conn, content, "card.pdf")

    assert second.added == 0
    assert second.duplicates == 3
    assert _count(conn) == 3


def test_overlapping_statements_add_only_the_missing_rows(conn) -> None:
    import_file(conn, _statement([SHOP, FEE, PAYMENT]), "july.pdf")

    result = import_file(conn, _statement([FEE, PAYMENT], [PHARMACY]), "august.pdf")

    assert result.added == 1
    assert result.duplicates == 2
    assert _count(conn) == 4


def test_two_identical_rows_in_one_file_are_both_kept(conn) -> None:
    result = import_file(conn, _statement([SHOP, SHOP]), "card.pdf")

    assert result.added == 2
    assert _count(conn) == 2


def test_same_rows_in_a_different_order_add_nothing(conn) -> None:
    import_file(conn, _statement([SHOP, FEE, PAYMENT]), "card.pdf")

    result = import_file(conn, _statement([PAYMENT, SHOP, FEE]), "reordered.pdf")

    assert result.added == 0
    assert result.duplicates == 3


def test_stored_row_keeps_source_card_label_dates_purpose_and_raw_row(conn) -> None:
    import_file(conn, _statement([SHOP]), "card.pdf")

    stored = conn.execute(
        "SELECT source, account, booking_date, value_date, amount_cents, currency, "
        "counterparty, purpose, raw_row FROM transactions"
    ).fetchone()

    assert stored == (
        SOURCE,
        CARD_LABEL,
        "2026-07-04",
        "2026-07-03",
        -123456,
        "EUR",
        "MUSTER MÖBELHAUS",
        "Ratenzahlung",
        "03.07.26 04.07.26 MUSTER MÖBELHAUS -1.234,56",
    )


def test_import_creates_no_account_or_balance_entity(conn) -> None:
    tables_before = {name for (name,) in conn.execute("SELECT name FROM sqlite_master")}

    import_file(conn, _statement([SHOP], [PHARMACY]), "card.pdf")

    assert {name for (name,) in conn.execute("SELECT name FROM sqlite_master")} == tables_before
    assert "accounts" not in tables_before
    assert _count(conn, "balances") == 0
