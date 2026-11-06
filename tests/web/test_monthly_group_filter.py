"""Monthly group links narrow only the payment list."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.web.app import create_app
from tests.html import cents, records, soup, text
from tests.seed import seed
from tests.web.test_monthly_page import FIXTURE, TOML


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "groups.db"
    taxonomy = TOML.replace('type = "variable"', 'type = "fixed"')
    taxonomy += """
[[category]]
name = "Shopping"
type = "lights_on"
[[category]]
name = "Fees"
type = "occasional"
[[rule]]
category = "Shopping"
counterparty = "ACME GmbH"
[[rule]]
category = "Fees"
counterparty = "Utility Co"
"""
    seed(db_path, taxonomy)
    with TestClient(create_app(db_path, today=lambda: date(2026, 11, 5))) as client:
        client.post("/import", files=[("files", ("giro.csv", FIXTURE.read_bytes(), "text/csv"))])
        yield client


@pytest.mark.parametrize(
    "group,hook,category,count,total,label",
    [
        ("fixed", "fixed", "Dining", 2, -5750, "Fixed payments"),
        ("lights_on", "lights-on", "Shopping", 1, -4550, "Keep the lights on"),
        ("occasional", "occasional", "Fees", 1, -8999, "Occasional payments"),
        ("transfer", "transfer", "Own transfers", 1, -216712, "Transfers"),
    ],
)
def test_group_stat_filters_and_toggles(client, group, hook, category, count, total, label):
    unfiltered = soup(client.get("/monthly?month=2026-09"))
    link = unfiltered.select_one(f"#stat-{hook}")
    assert link["href"] == f"/monthly?month=2026-09&group={group}"
    page = soup(client.get(link["href"]))
    rows = records(page.select_one("#payments"))
    assert len(rows) == count
    assert {row["category"] for row in rows} == {category}
    assert page.select_one(f"#stat-{hook}")["aria-current"] == "true"
    assert page.select_one(f"#stat-{hook}")["href"] == "/monthly?month=2026-09"
    banner = page.select_one("#group-filter")
    assert f"Only {label}" in text(banner)
    assert banner["data-count"] == str(count)
    assert cents(banner) == total
    assert page.select_one("#reset-group")["href"] == "/monthly?month=2026-09"
    assert (
        page.select_one('#category-totals [data-field="category"] a')["href"].find("group=") == -1
    )
    assert not page.select("#income-bar a")


def test_month_navigation_preserves_group(client):
    for month, hook in [("2026-10", "older-month"), ("2026-08", "newer-month")]:
        page = soup(client.get(f"/monthly?month={month}&group=fixed"))
        assert page.select_one(f"#{hook}")["href"] == "/monthly?month=2026-09&group=fixed"
        assert (
            page.select_one("#month-picker").parent.select_one('[name="group"]')["value"] == "fixed"
        )


def test_unknown_group_is_not_found(client):
    assert client.get("/monthly?month=2026-09&group=bogus").status_code == 404


def test_category_takes_precedence_and_drops_group(client):
    page = soup(client.get("/monthly?month=2026-09&category=Dining&group=transfer"))
    assert {row["category"] for row in records(page.select_one("#payments"))} == {"Dining"}
    assert page.select_one("#category-filter") is not None
    assert page.select_one("#group-filter") is None
    assert not page.select('[id^="stat-"][aria-current]')
    assert page.select_one("#month-picker").parent.select_one('[name="group"]') is None
