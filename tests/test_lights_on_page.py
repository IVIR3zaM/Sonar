"""The Keep-the-lights-on page: daily average per month, chart and table (SPEC §12, §13)."""

import math
import sqlite3
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar import lights_on
from sonar.app import create_app
from sonar.categorization.store import load_stored_taxonomy, transactions_with_category
from sonar.db import MIGRATIONS_DIR, apply_migrations
from tests.html import cents, records, soup, text
from tests.seed import seed

# Groceries and Transport are lights_on, Dining is occasional. Rules match the
# fake counterparties inserted below; the app's startup rule pass categorizes
# them (same pattern as test_dashboard_page.py).
TOML = """
[[category]]
name = "Groceries"
type = "lights_on"

[[category]]
name = "Transport"
type = "lights_on"

[[category]]
name = "Dining"
type = "occasional"

[[rule]]
category = "Groceries"
counterparty = "Fake Market"

[[rule]]
category = "Transport"
counterparty = "Fake Transit"

[[rule]]
category = "Dining"
counterparty = "Fake Bistro"
"""

# Same categories and rules, but Groceries and Transport moved to occasional,
# so no category is left in the lights_on group.
NO_LIGHTS_ON_TOML = TOML.replace('type = "lights_on"', 'type = "occasional"')

MONTHS = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)]


def _insert(
    db_path: Path, *, fingerprint: str, counterparty: str, booking_date: str, cents: int
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
                'test', 'acc', ?, ?, ?, 'EUR', ?, '', NULL, NULL, NULL, 'raw', ?, 1, NULL
            )
            """,
            (booking_date, booking_date, cents, counterparty, fingerprint),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_four_months(db_path: Path, toml_text: str) -> None:
    seed(db_path, toml_text)
    groceries = [3100, 2800, 6200, 4500]
    transport = [1550, 1400, 3100, 2250]
    dining = [800, 600, 1200, 900]
    for i, month in enumerate(MONTHS):
        _insert(
            db_path,
            fingerprint=f"g{i}",
            counterparty="Fake Market",
            booking_date=month.isoformat(),
            cents=-groceries[i],
        )
        _insert(
            db_path,
            fingerprint=f"t{i}",
            counterparty="Fake Transit",
            booking_date=month.isoformat(),
            cents=-transport[i],
        )
        _insert(
            db_path,
            fingerprint=f"d{i}",
            counterparty="Fake Bistro",
            booking_date=month.isoformat(),
            cents=-dining[i],
        )
    # A credit dated on April's last day, so `until` (the latest booking
    # date) reaches past April 1 and April counts as a complete month too.
    _insert(
        db_path,
        fingerprint="marker",
        counterparty="Unrelated",
        booking_date="2026-04-30",
        cents=100,
    )


def _actual_months(db_path: Path) -> list[lights_on.MonthSpend]:
    conn = sqlite3.connect(db_path)
    try:
        taxonomy = load_stored_taxonomy(conn)
        rows = transactions_with_category(conn)
    finally:
        conn.close()
    until = max(tx.booking_date for tx, _ in rows)
    return lights_on.month_spends(rows, taxonomy.categories, None, until)


def _round(amount: Fraction) -> int:
    # Half a cent rounds up, mirroring lights_on.py's own `_cents` helper.
    return math.floor(amount + Fraction(1, 2))


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "t.db"
    _seed_four_months(db_path, TOML)
    app = create_app(db_path)
    with TestClient(app) as client:
        client.db_path = db_path
        yield client


def test_daily_average_equals_the_three_month_average(client):
    months = _actual_months(client.db_path)
    forecast = lights_on.lights_on_forecast(months, 1)

    page = soup(client.get("/lights-on"))

    assert cents(page.select_one("#daily-average")) == forecast.expected_cents


def test_chart_has_one_polyline_per_series_with_one_point_per_month(client):
    months = _actual_months(client.db_path)

    page = soup(client.get("/lights-on"))

    chart = page.select_one("#lights-on-chart")
    assert chart is not None
    polylines = chart.find_all("polyline")
    # Total + Groceries + Transport + Occasional.
    assert len(polylines) == 4
    assert all(len(p["points"].split()) == len(months) for p in polylines)


def test_table_daily_averages_match_the_lights_on_module(client):
    months = _actual_months(client.db_path)

    page = soup(client.get("/lights-on"))

    rows = records(page.select_one("#lights-on-table"))
    assert len(rows) == len(months) == 4
    for row, month in zip(rows, months, strict=True):
        expected_groceries = _round(month.daily_by_category.get("Groceries", Fraction(0)))
        assert row["category-Groceries"] == expected_groceries
        assert row["occasional"] == _round(month.daily_occasional)


def test_no_complete_month_shows_the_empty_state(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, TOML)

    with TestClient(create_app(db_path)) as client:
        page = soup(client.get("/lights-on"))

    assert page.select_one("#lights-on-empty") is not None
    assert page.select_one("#lights-on-chart") is None
    assert page.select_one("#lights-on-table") is None


def test_no_lights_on_category_links_to_categories_and_chart_shows_occasional_only(tmp_path):
    db_path = tmp_path / "t.db"
    _seed_four_months(db_path, NO_LIGHTS_ON_TOML)

    with TestClient(create_app(db_path)) as client:
        page = soup(client.get("/lights-on"))

    notice = page.select_one("#lights-on-no-categories")
    assert notice is not None
    assert notice.select_one('a[href="/categories"]') is not None
    chart = page.select_one("#lights-on-chart")
    polylines = chart.find_all("polyline")
    assert len(polylines) == 1
    assert text(polylines[0].find("title")) or polylines[0]["data-series"]


def test_daily_average_card_shows_the_range_and_the_months_used(client):
    forecast = lights_on.lights_on_forecast(_actual_months(client.db_path), 1)

    page = soup(client.get("/lights-on"))

    assert cents(page.select_one("#daily-low")) == forecast.low_cents
    assert cents(page.select_one("#daily-high")) == forecast.high_cents
    used = page.select_one("#months-used")
    assert [t["datetime"] for t in used.select("time")] == ["2026-02-01", "2026-04-30"]


def test_rows_of_the_months_used_are_marked_and_calendar_months_are_named(client):
    page = soup(client.get("/lights-on"))

    rows = page.select("#lights-on-table [data-row]")
    assert [row.get("data-used") for row in rows] == [None, "true", "true", "true"]
    assert rows[0].select_one("[data-field=start] time")["datetime"] == "2026-01-01"
    assert rows[0].select_one("[data-field=end] time")["datetime"] == "2026-01-31"
    hint = page.select_one("#salary-day-hint")
    assert "Calendar months" in text(hint)
    assert hint.select_one('a[href="/settings"]') is not None


def test_salary_months_show_their_label_and_payday_to_payday_dates(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, TOML)
    for i, day in enumerate(["2026-03-01", "2026-04-15", "2026-05-15", "2026-06-10"]):
        _insert(
            db_path, fingerprint=f"s{i}", counterparty="Fake Market", booking_date=day, cents=-900
        )

    with TestClient(create_app(db_path)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        page = soup(client.get("/lights-on"))

    first = page.select_one("#lights-on-table [data-row]")
    assert "Mar 2026" in text(first.select_one("[data-field=month]"))
    start = first.select_one("[data-field=start] time")["datetime"]
    end = first.select_one("[data-field=end] time")["datetime"]
    assert not start.endswith("-01")
    assert not end.endswith("-01")
    assert page.select_one("#salary-day-hint") is None
    assert "Salary months" in text(page.select_one("#salary-months"))
