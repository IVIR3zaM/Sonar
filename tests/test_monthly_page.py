"""The Monthly spending page: category totals on top, the month's payments below."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.monthly import UNCATEGORIZED
from tests.html import cents, records, soup, text

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"

# The fixture's September debits: "Max Mustermann" -2,167.12 (a transfer
# here), two "Restaurant XYZ" -28.75, and "ACME GmbH" -45.50 plus
# "Utility Co" -89.99 left uncategorized. Its two credits are not payments;
# "John Doe" +1,234.56 on 22 Sep plays the salary.
TOML = """
[[category]]
name = "Salary"
type = "income"

[[category]]
name = "Dining"
type = "variable"

[[category]]
name = "Own transfers"
type = "transfer"

[[rule]]
category = "Dining"
counterparty = "Restaurant XYZ"

[[rule]]
category = "Own transfers"
counterparty = "Max Mustermann"

[[rule]]
category = "Salary"
counterparty = "John Doe"
"""


@pytest.fixture
def client(tmp_path):
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text(TOML, encoding="utf-8")
    # Pinned well after the fixture, so the default month cannot come from the clock.
    app = create_app(
        tmp_path / "t.db", categories_path=categories_path, today=lambda: date(2026, 11, 5)
    )
    with TestClient(app) as client:
        client.post("/import", files=[("files", ("giro.csv", FIXTURE.read_bytes(), "text/csv"))])
        yield client


def _period(page) -> tuple[str, str]:
    return page.select_one("#period-start")["datetime"], page.select_one("#period-end")["datetime"]


def test_defaults_to_the_latest_month_with_payments(client):
    page = soup(client.get("/monthly"))

    assert page.select_one("#month")["datetime"] == "2026-09"


def test_without_a_salary_day_months_are_calendar_months(client):
    page = soup(client.get("/monthly?month=2026-09"))

    assert _period(page) == ("2026-09-01", "2026-09-30")
    assert page.select_one("#salary-day-hint a[href='/settings']") is not None


def test_with_a_salary_day_a_month_starts_on_the_real_payday(client):
    client.post("/settings", data={"salary_day": "26", "overdraft_limit": "0"})

    # The salary promised for 25 Sep (the 26th is a Saturday) came early on
    # the 22nd, so September ends on the 21st and October starts on the 22nd.
    september = soup(client.get("/monthly?month=2026-09"))
    assert _period(september) == ("2026-08-26", "2026-09-21")
    assert september.select_one("#salary-day-hint") is None
    assert [row["counterparty"] for row in records(september.select_one("#payments"))] == [
        "Restaurant XYZ",
        "Utility Co",
        "Restaurant XYZ",
    ]

    october = soup(client.get("/monthly"))
    assert october.select_one("#month")["datetime"] == "2026-10"
    assert _period(october) == ("2026-09-22", "2026-10-25")
    assert [row["counterparty"] for row in records(october.select_one("#payments"))] == [
        "Max Mustermann",
        "ACME GmbH",
    ]


def test_shows_totals_per_category_and_for_the_month(client):
    page = soup(client.get("/monthly?month=2026-09"))

    assert records(page.select_one("#category-totals")) == [
        {"category": "Own transfers", "count": "1", "total": -216_712},
        {"category": "Uncategorized", "count": "2", "total": -13_549},
        {"category": "Dining", "count": "2", "total": -5_750},
    ]
    assert cents(page.select_one("#month-total")) == -19_299
    assert cents(page.select_one("#transfers-total")) == -216_712


def test_lists_the_months_payments_newest_first(client):
    page = soup(client.get("/monthly?month=2026-09"))

    rows = records(page.select_one("#payments"))
    assert [(row["date"], row["counterparty"], row["category"], row["amount"]) for row in rows] == [
        ("2026-09-23", "Max Mustermann", "Own transfers", -216_712),
        ("2026-09-22", "ACME GmbH", "Uncategorized", -4_550),
        ("2026-09-21", "Restaurant XYZ", "Dining", -2_875),
        ("2026-09-21", "Utility Co", "Uncategorized", -8_999),
        ("2026-09-21", "Restaurant XYZ", "Dining", -2_875),
    ]


def test_a_month_without_payments_shows_an_empty_state_and_links_back(client):
    page = soup(client.get("/monthly?month=2026-08"))

    assert page.select_one("#no-payments") is not None
    assert page.select_one("#payments") is None
    assert cents(page.select_one("#month-total")) == 0
    assert page.select_one("#newer-month")["href"] == "/monthly?month=2026-09"
    assert page.select_one("#older-month") is None


def test_the_month_picker_lists_months_with_payments(client):
    page = soup(client.get("/monthly?month=2026-09"))

    picker = page.select_one('form[action="/monthly"] select[name="month"]')
    assert [option["value"] for option in picker.select("option")] == ["2026-09"]
    assert picker.select_one("option[selected]")["value"] == "2026-09"


@pytest.mark.parametrize("month", ["2026-13", "september", ""])
def test_an_invalid_month_is_not_found(client, month):
    assert client.get(f"/monthly?month={month}").status_code == 404


def test_an_empty_database_still_renders(tmp_path):
    with TestClient(create_app(tmp_path / "t.db", today=lambda: date(2026, 9, 24))) as client:
        page = soup(client.get("/monthly"))

    assert page.select_one("#month")["datetime"] == "2026-09"
    assert page.select_one("#no-payments") is not None


def _selected(page) -> list[str]:
    rows = page.select('#category-totals [data-row][aria-current="true"]')
    return [text(row.select_one('[data-field="category"]')) for row in rows]


def test_each_category_links_to_the_list_filtered_to_it(client):
    page = soup(client.get("/monthly?month=2026-09"))

    links = [a["href"] for a in page.select('#category-totals [data-field="category"] a')]
    assert links == [
        "/monthly?month=2026-09&category=Own+transfers",
        f"/monthly?month=2026-09&category={UNCATEGORIZED}",
        "/monthly?month=2026-09&category=Dining",
    ]
    assert _selected(page) == []
    assert page.select_one("#reset-category") is None


def test_a_category_filter_narrows_the_payments_but_keeps_every_category(client):
    page = soup(client.get("/monthly?month=2026-09&category=Dining"))

    assert [row["counterparty"] for row in records(page.select_one("#payments"))] == [
        "Restaurant XYZ",
        "Restaurant XYZ",
    ]
    assert len(records(page.select_one("#category-totals"))) == 3
    assert _selected(page) == ["Dining"]
    # The month's totals stay those of the whole month.
    assert cents(page.select_one("#month-total")) == -19_299
    assert page.select_one("#reset-category")["href"] == "/monthly?month=2026-09"


def test_the_uncategorized_group_can_be_filtered_too(client):
    page = soup(client.get(f"/monthly?month=2026-09&category={UNCATEGORIZED}"))

    assert [row["counterparty"] for row in records(page.select_one("#payments"))] == [
        "ACME GmbH",
        "Utility Co",
    ]
    assert _selected(page) == ["Uncategorized"]


def test_switching_months_keeps_the_category_filter(client):
    page = soup(client.get("/monthly?month=2026-08&category=Dining"))

    assert page.select_one("#newer-month")["href"] == "/monthly?month=2026-09&category=Dining"
    picker = page.select_one('form[action="/monthly"]')
    assert picker.select_one('input[type="hidden"][name="category"]')["value"] == "Dining"
    # Nothing to list, but the filter is still on and can be reset.
    assert page.select_one("#no-payments") is not None
    assert page.select_one("#reset-category")["href"] == "/monthly?month=2026-08"


def test_category_and_month_links_swap_the_page_in_place(client):
    page = soup(client.get("/monthly?month=2026-09&category=Dining"))

    # Boosted links swap <main> without scrolling to the top; the rest of the
    # page's links (e.g. Settings) stay plain so the sidebar is redrawn.
    for selector in ["#category-totals", "#reset-category", "#month-picker"]:
        boosted = page.select_one(selector).find_parent(attrs={"hx-boost": "true"})
        assert boosted["hx-select"] == "#main"
        assert "show:none" in boosted["hx-swap"]
