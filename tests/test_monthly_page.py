"""The Monthly spending page: category totals on top, the month's payments below."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations
from sonar.monthly import UNCATEGORIZED
from sonar.taxonomy_service import reapply_stored_taxonomy
from sonar.taxonomy_store import list_categories, update_category
from tests.html import cents, records, soup, text
from tests.seed import seed

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"
MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"

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
    db_path = tmp_path / "t.db"
    seed(db_path, TOML)
    # Pinned well after the fixture, so the default month cannot come from the clock.
    app = create_app(db_path, today=lambda: date(2026, 11, 5))
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
        {"category": "Uncategorized", "group": "", "count": "2", "total": -13_549},
        {"category": "Dining", "group": "Occasional payments", "count": "2", "total": -5_750},
    ]
    assert records(page.select_one("#transfer-totals")) == [
        {"category": "Own transfers", "group": "Transfers", "count": "1", "total": -216_712},
    ]
    assert cents(page.select_one("#month-total")) == -19_299
    assert cents(page.select_one("#transfers-net")) == -216_712
    assert sum(row["total"] for row in records(page.select_one("#transfer-totals"))) == cents(
        page.select_one("#transfers-net")
    )


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
        f"/monthly?month=2026-09&category={UNCATEGORIZED}",
        "/monthly?month=2026-09&category=Dining",
    ]
    transfer_links = [a["href"] for a in page.select('#transfer-totals [data-field="category"] a')]
    assert transfer_links == ["/monthly?month=2026-09&category=Own+transfers"]
    assert _selected(page) == []
    assert page.select_one("#reset-category") is None


def test_a_category_filter_narrows_the_payments_but_keeps_every_category(client):
    page = soup(client.get("/monthly?month=2026-09&category=Dining"))

    assert [row["counterparty"] for row in records(page.select_one("#payments"))] == [
        "Restaurant XYZ",
        "Restaurant XYZ",
    ]
    assert len(records(page.select_one("#category-totals"))) == 2
    assert len(records(page.select_one("#transfer-totals"))) == 1
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


def test_a_transfer_category_can_still_be_filtered(client):
    page = soup(client.get("/monthly?month=2026-09&category=Own+transfers"))

    assert [row["counterparty"] for row in records(page.select_one("#payments"))] == [
        "Max Mustermann",
    ]
    row = page.select_one('#transfer-totals [data-row][aria-current="true"]')
    assert text(row.select_one('[data-field="category"]')) == "Own transfers"
    assert page.select_one("#category-filter") is not None
    assert page.select_one("#reset-category")["href"] == "/monthly?month=2026-09"


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


# One category per N02 group plus a transfer out and back; counterparties are
# fake and matched by rules, so the app's own startup rule pass categorizes
# them (like GROUPS_TOML in test_dashboard_page.py) instead of pre-set values.
GROUPS_TOML = """
[[category]]
name = "Housing"
type = "fixed"

[[category]]
name = "Groceries"
type = "lights_on"

[[category]]
name = "Dining"
type = "occasional"

[[category]]
name = "Own transfers"
type = "transfer"

[[rule]]
category = "Housing"
counterparty = "Fake Landlord"

[[rule]]
category = "Groceries"
counterparty = "Fake Market"

[[rule]]
category = "Dining"
counterparty = "Fake Cafe"

[[rule]]
category = "Own transfers"
counterparty = "Fake Own Account"
"""


def _insert(
    db_path: Path, *, fingerprint: str, booking_date: str, amount_cents: int, counterparty: str
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        conn.execute(
            """
            INSERT INTO transactions (
                source, account, booking_date, value_date, amount_cents, currency,
                counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                fingerprint, occurrence, category
            ) VALUES (
                'test', 'acc', ?, ?, ?, 'EUR', ?, '', NULL, NULL, NULL,
                'raw', ?, 1, NULL
            )
            """,
            (booking_date, booking_date, amount_cents, counterparty, fingerprint),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def groups_client(tmp_path):
    db_path = tmp_path / "groups.db"
    seed(db_path, GROUPS_TOML)
    _insert(
        db_path,
        fingerprint="h1",
        booking_date="2026-09-05",
        amount_cents=-100_000,
        counterparty="Fake Landlord",
    )
    _insert(
        db_path,
        fingerprint="g1",
        booking_date="2026-09-06",
        amount_cents=-3_000,
        counterparty="Fake Market",
    )
    _insert(
        db_path,
        fingerprint="d1",
        booking_date="2026-09-07",
        amount_cents=-2_000,
        counterparty="Fake Cafe",
    )
    _insert(
        db_path,
        fingerprint="t1",
        booking_date="2026-09-08",
        amount_cents=-10_000,
        counterparty="Fake Own Account",
    )
    _insert(
        db_path,
        fingerprint="t2",
        booking_date="2026-09-09",
        amount_cents=9_000,
        counterparty="Fake Own Account",
    )
    with TestClient(create_app(db_path, today=lambda: date(2026, 9, 24))) as client:
        yield client, db_path


def _transfers_label(page) -> str:
    return text(page.select_one("#transfers-net").find_parent("div").select_one("p"))


def test_group_totals_sum_to_the_spent_total(groups_client):
    client, _ = groups_client
    page = soup(client.get("/monthly?month=2026-09"))

    assert cents(page.select_one("#group-fixed")) == -100_000
    assert cents(page.select_one("#group-lights-on")) == -3_000
    assert cents(page.select_one("#group-occasional")) == -2_000
    assert (
        cents(page.select_one("#group-fixed"))
        + cents(page.select_one("#group-lights-on"))
        + cents(page.select_one("#group-occasional"))
        == cents(page.select_one("#month-total"))
        == -105_000
    )


def test_net_transfers_negative_when_more_goes_out(groups_client):
    client, _ = groups_client
    page = soup(client.get("/monthly?month=2026-09"))

    assert cents(page.select_one("#transfers-net")) == -1_000
    assert _transfers_label(page) == "Net moved to other accounts"


def test_net_transfers_positive_when_more_comes_back(tmp_path):
    db_path = tmp_path / "back.db"
    seed(db_path, GROUPS_TOML)
    _insert(
        db_path,
        fingerprint="t1",
        booking_date="2026-09-08",
        amount_cents=-5_000,
        counterparty="Fake Own Account",
    )
    _insert(
        db_path,
        fingerprint="t2",
        booking_date="2026-09-09",
        amount_cents=9_000,
        counterparty="Fake Own Account",
    )
    with TestClient(create_app(db_path, today=lambda: date(2026, 9, 24))) as client:
        page = soup(client.get("/monthly?month=2026-09"))

    assert cents(page.select_one("#transfers-net")) == 4_000
    assert _transfers_label(page) == "Net received from other accounts"


def test_category_rows_carry_a_group_badge(groups_client):
    client, _ = groups_client
    page = soup(client.get("/monthly?month=2026-09"))

    rows = {row["category"]: row["group"] for row in records(page.select_one("#category-totals"))}
    assert rows["Groceries"] == "Keep the lights on"
    assert rows["Dining"] == "Occasional payments"
    assert rows["Housing"] == "Fixed payments"
    assert "Own transfers" not in rows

    transfer_rows = {
        row["category"]: row["group"] for row in records(page.select_one("#transfer-totals"))
    }
    assert transfer_rows["Own transfers"] == "Transfers"


def test_changing_a_categorys_group_through_the_store_moves_its_total(groups_client):
    client, db_path = groups_client
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        dining = next(c for c in list_categories(conn) if c.name == "Dining")
        update_category(conn, dining.id, dining.name, "lights_on")
        reapply_stored_taxonomy(conn, date(2026, 9, 24))
    finally:
        conn.close()

    page = soup(client.get("/monthly?month=2026-09"))

    assert cents(page.select_one("#group-lights-on")) == -5_000
    assert cents(page.select_one("#group-occasional")) == 0
