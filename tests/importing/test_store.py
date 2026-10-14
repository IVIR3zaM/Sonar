"""Tests for importing a bank export into the database (SPEC §4, incl. Idempotency)."""

import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from sonar.categorization.rules import parse_taxonomy
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.importing.importers import UnknownFormatError, deutsche_bank_giro
from sonar.importing.store import import_file, import_rows
from sonar.transactions import ParsedBalance, ParsedTransaction

FIXTURE = Path(__file__).parent.parent / "fixtures" / "db_girokonto.csv"

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
    monkeypatch.setattr("sonar.importing.store.pick_importer", lambda content: stub)

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


# --- Bank sync overlap (SPEC §13 Bank sync): one booking from a CSV and the API is stored once.

_API = "Enable Banking"


def _csv_transactions() -> list[ParsedTransaction]:
    return deutsche_bank_giro.parse(FIXTURE.read_bytes())


def _api_transactions() -> list[ParsedTransaction]:
    # The sync reports the same bookings with a shorter, padded purpose and no mandate data.
    return [
        replace(
            tx,
            purpose=f"  {tx.purpose[:8].upper()} ",
            mandate_ref=None,
            creditor_id=None,
            raw_row="{}",
            entry_reference=f"ref-{n}",
        )
        for n, tx in enumerate(_csv_transactions())
    ]


def test_api_rows_store_their_entry_reference(conn) -> None:
    result = import_rows(conn, _API, _api_transactions()[:1])

    stored = conn.execute(
        "SELECT source, entry_reference, merged, occurrence FROM transactions"
    ).fetchall()
    assert result.added == 1
    assert stored == [(_API, "ref-0", 0, 1)]


def test_csv_then_api_leaves_one_row_per_booking(conn) -> None:
    import_file(conn, FIXTURE.read_bytes(), "giro.csv")

    result = import_rows(conn, _API, _api_transactions())

    assert result.added == 0
    assert result.duplicates == _FIXTURE_ROWS
    assert _count_transactions(conn) == _FIXTURE_ROWS
    merged = conn.execute(
        "SELECT source, purpose, entry_reference, merged FROM transactions WHERE id = 1"
    ).fetchone()
    assert merged == ("Deutsche Bank Girokonto CSV", "Salary payment; ref: ABC123", "ref-0", 1)


def test_api_then_csv_leaves_one_row_and_fills_in_the_csv_details(conn) -> None:
    import_rows(conn, _API, _api_transactions())

    result = import_file(conn, FIXTURE.read_bytes(), "giro.csv")

    assert result.added == 0
    assert result.duplicates == _FIXTURE_ROWS
    assert _count_transactions(conn) == _FIXTURE_ROWS
    merged = conn.execute(
        "SELECT source, purpose, mandate_ref, creditor_id, entry_reference, merged "
        "FROM transactions WHERE entry_reference = 'ref-0'"
    ).fetchone()
    assert merged == (
        _API,
        "Salary payment; ref: ABC123",
        "MND123",
        "DE11ZZZ00000000001",
        "ref-0",
        1,
    )


@pytest.mark.parametrize("api_first", [True, False])
def test_rerunning_either_import_after_a_merge_adds_nothing(conn, api_first) -> None:
    def csv() -> int:
        return import_file(conn, FIXTURE.read_bytes(), "giro.csv").added

    def api() -> int:
        return import_rows(conn, _API, _api_transactions()).added

    first, second = (api, csv) if api_first else (csv, api)
    first()
    second()

    assert (csv(), api()) == (0, 0)
    assert _count_transactions(conn) == _FIXTURE_ROWS


def test_api_refetch_adds_nothing(conn) -> None:
    import_rows(conn, _API, _api_transactions())

    result = import_rows(conn, _API, _api_transactions())

    assert result.added == 0
    assert result.duplicates == _FIXTURE_ROWS
    assert _count_transactions(conn) == _FIXTURE_ROWS


def test_two_identical_same_day_api_rows_are_both_stored(conn) -> None:
    tx = _api_transactions()[0]
    twins = [replace(tx, entry_reference="a"), replace(tx, entry_reference="b")]

    result = import_rows(conn, _API, twins)

    assert result.added == 2
    assert _count_transactions(conn) == 2


def test_api_row_does_not_merge_into_another_api_row(conn) -> None:
    tx = _api_transactions()[0]
    import_rows(conn, _API, [replace(tx, entry_reference="a")])

    result = import_rows(conn, _API, [replace(tx, entry_reference="b")])

    assert result.added == 1
    assert _count_transactions(conn) == 2


def test_import_rows_stores_the_balance_and_applies_rules(conn) -> None:
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
    balance = ParsedBalance(account="123 4567890 01", as_of=date(2026, 10, 1), amount_cents=100)

    result = import_rows(conn, _API, _api_transactions(), balance=balance, rules=taxonomy.rules)

    assert result.uncategorized == _FIXTURE_ROWS - 1
    assert conn.execute("SELECT as_of, amount_cents FROM balances").fetchall() == [
        ("2026-10-01", 100)
    ]
