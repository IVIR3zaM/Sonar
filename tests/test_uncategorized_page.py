"""Tests for the Uncategorized page: export text, table, and re-apply (SPEC §5, §11)."""

from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.uncategorized_export import HEADER
from tests.html import records, soup, text
from tests.seed import seed

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"

# No rules at all: every imported row of the fixture stays uncategorized.
EMPTY_TOML = ""

RESTAURANT_RULE_TOML = """
[[category]]
name = "Dining"
type = "variable"

[[rule]]
category = "Dining"
counterparty = "Restaurant XYZ"
"""

RESTAURANT_AND_ACME_TOML = """
[[category]]
name = "Dining"
type = "variable"

[[category]]
name = "Subscriptions"
type = "fixed"

[[rule]]
category = "Dining"
counterparty = "Restaurant XYZ"

[[rule]]
category = "Subscriptions"
counterparty = "ACME GmbH"
"""


def _count(response) -> int:
    return int(text(soup(response).select_one("#uncategorized-count")))


def test_uncategorized_page_lists_header_groups_and_reapply_narrows_them(tmp_path):
    content = FIXTURE.read_bytes()
    db_path = tmp_path / "t.db"
    seed(db_path, EMPTY_TOML)

    with TestClient(create_app(db_path)) as client:
        upload = client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])
        # All 7 rows added, none matched by the empty taxonomy.
        [giro] = soup(upload).select('[data-filename="giro.csv"]')
        assert int(text(giro.select_one('[data-field="added"]'))) == 7

        page = client.get("/uncategorized")
        assert page.status_code == 200
        request_text = soup(page).select_one("#categorization-request").get_text()
        # Exact first line of the copy-to-Claude-Code export.
        assert request_text.splitlines()[0] == HEADER
        # The fixture's two identical "Restaurant XYZ" rows form one group.
        assert (
            "2x restaurant xyz | -28.75..-28.75 EUR | 2026-09-21..2026-09-21 "
            "| Dinner with colleagues" in request_text
        )
        assert _count(page) == 7
        rows = records(soup(page).select_one("#transactions"))
        assert len(rows) == 7
        # The row table shows the raw counterparty, with its amount in cents.
        restaurant_rows = [row for row in rows if row["counterparty"] == "Restaurant XYZ"]
        assert [(row["date"], row["amount"]) for row in restaurant_rows] == [
            ("2026-09-21", -2_875),
            ("2026-09-21", -2_875),
        ]

        # Add a rule for "Restaurant XYZ" and re-upload the same file: no
        # duplicates are added, but the previously stored matching rows are
        # now categorized and disappear from the page.
        seed(db_path, RESTAURANT_RULE_TOML)
        reupload = client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])
        [giro] = soup(reupload).select('[data-filename="giro.csv"]')
        assert int(text(giro.select_one('[data-field="added"]'))) == 0  # all duplicates

        page_after = client.get("/uncategorized")
        assert _count(page_after) == 5
        assert "restaurant xyz" not in text(soup(page_after)).casefold()

        # A further rule change without re-uploading takes effect via /reapply.
        seed(db_path, RESTAURANT_AND_ACME_TOML)
        reapply = client.post("/reapply")
        assert reapply.status_code == 200
        assert _count(reapply) == 4

        page_final = client.get("/uncategorized")
        assert _count(page_final) == 4
        assert len(records(soup(page_final).select_one("#transactions"))) == 4


def test_nav_links_to_uncategorized_page(tmp_path):
    # The /import page has no other link to /uncategorized, so this only
    # passes if base.html's shared nav carries the link.
    with TestClient(create_app(tmp_path / "t.db")) as client:
        response = client.get("/import")

    assert soup(response).select_one('a[href="/uncategorized"]') is not None


def test_reapply_button_has_loading_indicator_and_copy_targets_the_request_panel(tmp_path):
    with TestClient(create_app(tmp_path / "t.db")) as client:
        page = soup(client.get("/uncategorized"))

    reapply = page.select_one('[hx-post="/reapply"]')
    assert reapply is not None
    indicator_id = reapply["hx-indicator"].lstrip("#")
    assert page.select_one(f"#{indicator_id}") is not None

    copy_button = page.select_one("#copy-request")
    assert copy_button is not None
    assert page.select_one("#categorization-request") is not None


def test_copy_button_falls_back_when_clipboard_is_unavailable_or_rejects(tmp_path):
    with TestClient(create_app(tmp_path / "t.db")) as client:
        page = client.get("/uncategorized")

    scripts = "\n".join(tag.get_text() for tag in soup(page).select("script"))
    # Both the success and fallback button texts must be reachable from script.
    assert "Copied" in scripts
    assert "Press ⌘C / Ctrl+C" in scripts
    # A clipboard existence check, so old browsers/denied permissions fall back.
    assert "navigator.clipboard" in scripts and "writeText" in scripts
    # writeText().then(success, rejection) -- a rejection handler runs the fallback.
    assert ".then(succeeded, fallback)" in scripts
    # The fallback selects the #categorization-request text for manual copying.
    assert 'getElementById("categorization-request")' in scripts
    assert "getSelection" in scripts and "selectNodeContents" in scripts


def test_row_amounts_carry_data_cents(tmp_path):
    content = FIXTURE.read_bytes()
    db_path = tmp_path / "t.db"
    seed(db_path, EMPTY_TOML)

    with TestClient(create_app(db_path)) as client:
        client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])
        page = soup(client.get("/uncategorized"))

    cells = page.select_one("#transactions").select('[data-field="amount"] [data-cents]')
    assert cells, "expected at least one amount cell with data-cents"
    for cell in cells:
        int(cell["data-cents"])  # every amount is a parseable integer of cents
