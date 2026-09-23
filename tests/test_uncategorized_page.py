"""Tests for the Uncategorized page: export text, table, and re-apply (SPEC §5, §11)."""

from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.uncategorized_export import HEADER

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


def test_uncategorized_page_lists_header_groups_and_reapply_narrows_them(tmp_path):
    content = FIXTURE.read_bytes()
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text(EMPTY_TOML, encoding="utf-8")

    with TestClient(create_app(tmp_path / "t.db", categories_path=categories_path)) as client:
        upload = client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])
        assert ">7<" in upload.text  # all 7 rows added, none matched by the empty taxonomy

        page = client.get("/uncategorized")
        assert page.status_code == 200
        # Exact first line of the copy-to-Claude-Code export.
        assert HEADER in page.text
        # The fixture's two identical "Restaurant XYZ" rows form one group.
        assert (
            "2x restaurant xyz | -28.75..-28.75 EUR | 2026-09-21..2026-09-21 "
            "| Dinner with colleagues" in page.text
        )
        assert 'id="uncategorized-count">7<' in page.text
        assert "Restaurant XYZ" in page.text  # row table shows the raw counterparty

        # Add a rule for "Restaurant XYZ" and re-upload the same file: no
        # duplicates are added, but the previously stored matching rows are
        # now categorized and disappear from the page.
        categories_path.write_text(RESTAURANT_RULE_TOML, encoding="utf-8")
        reupload = client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])
        assert ">0<" in reupload.text  # 0 rows added, all duplicates

        page_after = client.get("/uncategorized")
        assert 'id="uncategorized-count">5<' in page_after.text
        assert "restaurant xyz" not in page_after.text.casefold()

        # A further rule change without re-uploading takes effect via /reapply.
        categories_path.write_text(RESTAURANT_AND_ACME_TOML, encoding="utf-8")
        reapply = client.post("/reapply")
        assert reapply.status_code == 200
        assert 'id="uncategorized-count">4<' in reapply.text

        page_final = client.get("/uncategorized")
        assert 'id="uncategorized-count">4<' in page_final.text


def test_nav_links_to_uncategorized_page(tmp_path):
    # The /import page has no other link to /uncategorized, so this only
    # passes if base.html's shared nav carries the link.
    with TestClient(create_app(tmp_path / "t.db")) as client:
        response = client.get("/import")

    assert 'href="/uncategorized"' in response.text
