"""Tests for importing a bank export into the database (SPEC §4, incl. Idempotency)."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sonar.categorize import parse_taxonomy
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.importers import UnknownFormatError, deutsche_bank_giro
from sonar.importing import import_file

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"

# The fixture has 7 preamble lines, the header, 7 data rows and a footer line.
_HEADER_END = 8
_FIXTURE_ROWS = 7


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _fixture_parts() -> tuple[list[bytes], list[bytes], list[bytes]]:
    lines = FIXTURE.read_bytes().splitlines(keepends=True)
    return lines[:_HEADER_END], lines[_HEADER_END:-1], lines[-1:]


def _export_with_rows(rows: list[bytes]) -> bytes:
    head, _, footer = _fixture_parts()
    return b"".join(head + rows + footer)


def _count_transactions(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


def test_first_import_adds_every_row_and_reports_the_format(conn) -> None:
    result = import_file(conn, FIXTURE.read_bytes(), "giro.csv")

    assert result.filename == "giro.csv"
    assert result.format == "Deutsche Bank Girokonto CSV"
    assert result.added == _FIXTURE_ROWS
    assert result.duplicates == 0
    assert result.uncategorized == _FIXTURE_ROWS
    assert _count_transactions(conn) == _FIXTURE_ROWS


def test_same_file_imported_twice_adds_nothing_the_second_time(conn) -> None:
    content = FIXTURE.read_bytes()
    import_file(conn, content, "giro.csv")

    second = import_file(conn, content, "giro.csv")

    assert second.added == 0
    assert second.duplicates == _FIXTURE_ROWS
    assert second.uncategorized == 0
    assert _count_transactions(conn) == _FIXTURE_ROWS


def test_overlapping_files_add_only_the_missing_rows(conn) -> None:
    _, rows, _ = _fixture_parts()
    # Rows 2-4 appear in both date ranges; row 5 is new in the later export.
    earlier, overlap, later_only = rows[:5], rows[2:5], [rows[5]]
    import_file(conn, _export_with_rows(earlier), "earlier.csv")

    result = import_file(conn, _export_with_rows(overlap + later_only), "later.csv")

    assert result.added == 1
    assert result.duplicates == 3
    assert _count_transactions(conn) == 6


def test_two_identical_rows_in_one_file_are_both_kept(conn) -> None:
    _, rows, _ = _fixture_parts()
    identical = [rows[0], rows[0]]

    result = import_file(conn, _export_with_rows(identical), "giro.csv")

    assert result.added == 2
    assert _count_transactions(conn) == 2


def test_same_file_with_rows_reordered_adds_nothing(conn) -> None:
    _, rows, _ = _fixture_parts()
    import_file(conn, _export_with_rows(rows), "giro.csv")

    result = import_file(conn, _export_with_rows(list(reversed(rows))), "reordered.csv")

    assert result.added == 0
    assert result.duplicates == _FIXTURE_ROWS


def test_stored_row_keeps_source_account_and_optional_fields(conn) -> None:
    _, rows, _ = _fixture_parts()
    import_file(conn, _export_with_rows([rows[0]]), "giro.csv")

    stored = conn.execute(
        "SELECT source, account, booking_date, value_date, amount_cents, currency, "
        "counterparty, purpose, iban, mandate_ref, creditor_id, occurrence "
        "FROM transactions"
    ).fetchone()

    assert stored == (
        "Deutsche Bank Girokonto CSV",
        "123 4567890 01",
        "2026-09-23",
        "2026-09-23",
        -216712,
        "EUR",
        "Max Mustermann",
        "Salary payment; ref: ABC123",
        "DE89123456789012345678",
        "MND123",
        "DE11ZZZ00000000001",
        1,
    )


def test_balance_is_stored_with_its_date_once_across_reimports(conn) -> None:
    content = FIXTURE.read_bytes()
    import_file(conn, content, "giro.csv")
    import_file(conn, content, "giro.csv")

    balances = conn.execute("SELECT account, as_of, amount_cents, source FROM balances").fetchall()

    assert balances == [("123 4567890 01", "2026-09-23", -44843, "import")]


def test_import_persists_after_commit(tmp_path) -> None:
    db_path = tmp_path / "sonar.db"
    writer = sqlite3.connect(db_path)
    apply_migrations(writer, MIGRATIONS_DIR)
    import_file(writer, FIXTURE.read_bytes(), "giro.csv")

    reader = sqlite3.connect(db_path)

    assert _count_transactions(reader) == _FIXTURE_ROWS


def test_unknown_format_raises_and_stores_nothing(conn) -> None:
    with pytest.raises(UnknownFormatError):
        import_file(conn, b"date,amount\n2026-01-01,1.00\n", "other.csv")

    assert _count_transactions(conn) == 0


def test_importer_without_parse_balance_leaves_balances_table_empty(conn, monkeypatch) -> None:
    # Importers aren't required to expose parse_balance; import_file must not assume it does.
    content = FIXTURE.read_bytes()
    stub = SimpleNamespace(
        NAME="Stub CSV",
        detect=lambda content: True,
        parse=deutsche_bank_giro.parse,
    )
    monkeypatch.setattr("sonar.importing.pick_importer", lambda content: stub)

    result = import_file(conn, content, "giro.csv")

    assert result.added == _FIXTURE_ROWS
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0


def test_import_without_balance_footer_stores_rows_but_no_balance(conn) -> None:
    head, rows, _ = _fixture_parts()
    content = b"".join(head + rows)  # no "Account balance" footer line

    result = import_file(conn, content, "giro.csv")

    assert result.added == _FIXTURE_ROWS
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0


def test_import_applies_rules_to_this_files_new_rows(conn) -> None:
    # Only "ACME GmbH" (one row) matches; the other 6 new rows stay uncategorized.
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Subscriptions"
        type = "fixed"

        [[rule]]
        category = "Subscriptions"
        counterparty = "ACME"
        """
    )

    result = import_file(conn, FIXTURE.read_bytes(), "giro.csv", rules=taxonomy.rules)

    assert result.added == _FIXTURE_ROWS
    assert result.uncategorized == _FIXTURE_ROWS - 1
    categorized = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE category = 'Subscriptions'"
    ).fetchone()[0]
    assert categorized == 1


def test_reimport_with_a_new_rule_categorizes_previously_stored_rows(conn) -> None:
    content = FIXTURE.read_bytes()
    import_file(conn, content, "giro.csv")  # no rules yet: everything stays uncategorized

    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Invoices"
        type = "income"

        [[rule]]
        category = "Invoices"
        counterparty = "John Doe"
        """
    )
    result = import_file(conn, content, "giro.csv", rules=taxonomy.rules)

    assert result.added == 0
    assert result.duplicates == _FIXTURE_ROWS
    categorized = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE category = 'Invoices'"
    ).fetchone()[0]
    assert categorized == 1
