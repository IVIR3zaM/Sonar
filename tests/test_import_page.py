"""Tests for the upload page: GET /import form and POST /import results (SPEC §4)."""

from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"


def test_get_import_shows_upload_form(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "t.db")) as client:
        response = client.get("/import")

    assert response.status_code == 200
    assert "<form" in response.text
    assert "multiple" in response.text
    assert "Import" in response.text


def test_posting_fixture_twice_and_a_junk_file_reports_per_file_results(tmp_path) -> None:
    content = FIXTURE.read_bytes()

    with TestClient(create_app(tmp_path / "t.db")) as client:
        first = client.post(
            "/import",
            files=[("files", ("giro.csv", content, "text/csv"))],
        )
        second = client.post(
            "/import",
            files=[
                ("files", ("giro.csv", content, "text/csv")),
                ("files", ("junk.csv", b"not,a,bank,export\n1,2,3,4\n", "text/csv")),
            ],
        )

    assert first.status_code == 200
    assert "giro.csv" in first.text
    assert "Deutsche Bank Girokonto CSV" in first.text
    assert ">7<" in first.text  # 7 rows added on the first import

    assert second.status_code == 200
    # Re-importing the same file adds 0 rows the second time.
    assert ">0<" in second.text
    # The junk file must show its error in the error column (colspan="4").
    # Extract junk.csv's row (the one with colspan="4" for its error).
    import re

    junk_row_match = re.search(
        r'<tr><td>junk\.csv</td><td colspan="4">(.+?)</td></tr>',
        second.text,
    )
    assert junk_row_match, "junk.csv row with error not found in response"
    junk_error = junk_row_match.group(1)
    assert "Unrecognized file format" in junk_error
    assert "Supported formats: Deutsche Bank Girokonto CSV" in junk_error


def test_nav_links_to_import_page(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "t.db")) as client:
        response = client.get("/")

    assert 'href="/import"' in response.text


def test_upload_reports_per_file_uncategorized_from_tmp_toml(tmp_path) -> None:
    content = FIXTURE.read_bytes()
    # Never the shipped src/sonar/categories.toml: a fake rule matching one
    # of the fixture's counterparties, so exactly one row of the fixture's
    # 7 gets categorized and the rest stay uncategorized.
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text(
        """
        [[category]]
        name = "Groceries"
        type = "variable"

        [[rule]]
        category = "Groceries"
        counterparty = "ACME GmbH"
        """,
        encoding="utf-8",
    )

    with TestClient(create_app(tmp_path / "t.db", categories_path=categories_path)) as client:
        response = client.post(
            "/import",
            files=[("files", ("giro.csv", content, "text/csv"))],
        )

    assert response.status_code == 200
    assert "giro.csv" in response.text
    assert ">7<" in response.text  # rows added
    assert ">6<" in response.text  # 7 added, 1 categorized by the fake rule
