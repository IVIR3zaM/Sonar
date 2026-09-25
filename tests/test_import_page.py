"""Tests for the upload page: GET /import form and POST /import results (SPEC §4)."""

from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from tests.html import fields, soup
from tests.seed import seed

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"


def _results(response) -> dict[str, dict[str, int | str]]:
    """Each uploaded file's result fields, keyed by filename."""
    return {row["data-filename"]: fields(row) for row in soup(response).select("[data-filename]")}


def test_get_import_shows_upload_form(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "t.db")) as client:
        response = client.get("/import")

    assert response.status_code == 200
    page = soup(response)
    form = page.select_one('form[hx-post="/import"]')
    assert form["hx-target"] == "#results"
    dropzone = form.select_one("#dropzone")
    assert dropzone is not None
    assert dropzone.select_one('input[type="file"][name="files"][multiple]') is not None
    # The hx-indicator selector points at an element actually on the page.
    indicator_selector = form["hx-indicator"]
    assert page.select_one(indicator_selector) is not None
    assert page.select_one("#results") is not None


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
    first_page = soup(first)
    giro = _results(first)["giro.csv"]
    assert giro["format"] == "Deutsche Bank Girokonto CSV"
    assert int(giro["added"]) == 7
    # Counts render as badges, not bare numbers.
    added_badge = first_page.select_one(
        '[data-filename="giro.csv"] [data-field="added"] [data-tone]'
    )
    assert added_badge is not None
    assert added_badge["data-tone"] == "positive"

    assert second.status_code == 200
    second_page = soup(second)
    second_results = _results(second)
    # Re-importing the same file adds 0 rows the second time.
    assert int(second_results["giro.csv"]["added"]) == 0
    assert int(second_results["giro.csv"]["duplicates"]) == 7
    junk = second_results["junk.csv"]
    assert "added" not in junk
    assert "Unrecognized file format" in junk["error"]
    assert "Supported formats: Deutsche Bank Girokonto CSV" in junk["error"]
    # The unknown-format row is announced as an alert.
    junk_row = second_page.select_one('[data-filename="junk.csv"]')
    assert junk_row["role"] == "alert"
    giro_row = second_page.select_one('[data-filename="giro.csv"]')
    assert not giro_row.has_attr("role")


def test_dropzone_accepts_dropped_files(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "t.db")) as client:
        response = client.get("/import")

    page = soup(response)
    dropzone = page.select_one("#dropzone")
    assert dropzone.select_one('input[type="file"][name="files"]') is not None
    assert dropzone.select_one("#dropzone-filenames") is not None

    scripts = [tag.text for tag in page.find_all("script")]
    dropzone_script = next((s for s in scripts if "dataTransfer.files" in s), None)
    assert dropzone_script is not None
    assert "dragover" in dropzone_script
    assert "preventDefault" in dropzone_script


def test_nav_links_to_import_page(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "t.db")) as client:
        response = client.get("/")

    assert soup(response).select_one('a[href="/import"]') is not None


def test_upload_reports_per_file_uncategorized_from_tmp_toml(tmp_path) -> None:
    content = FIXTURE.read_bytes()
    db_path = tmp_path / "t.db"
    # Never the shipped src/sonar/categories.toml: a fake rule matching one
    # of the fixture's counterparties, so exactly one row of the fixture's
    # 7 gets categorized and the rest stay uncategorized.
    seed(
        db_path,
        """
        [[category]]
        name = "Groceries"
        type = "variable"

        [[rule]]
        category = "Groceries"
        counterparty = "ACME GmbH"
        """,
    )

    with TestClient(create_app(db_path)) as client:
        response = client.post(
            "/import",
            files=[("files", ("giro.csv", content, "text/csv"))],
        )

    assert response.status_code == 200
    giro = _results(response)["giro.csv"]
    assert int(giro["added"]) == 7
    assert int(giro["uncategorized"]) == 6  # 7 added, 1 categorized by the fake rule
