"""Tests for the dashboard page (SPEC §9): GET / renders load_dashboard's figures.

Seed data for the row-scoped test is picked so the numbers can be checked by
hand: salary day 26 and today 2026-09-10 give payday Friday 2026-09-25 (the
26th is a Saturday) and a window of [2026-09-11, 2026-09-24] (14 days) once
the balance is set as of today. Three Groceries debits, one per complete
salary cycle before that window, give an exact 25th/75th percentile range.
"""

import re
import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 10)

# Groceries is `variable` and matches the fake counterparty "Fake Market", so
# the seeded debits below are categorized by the app's own startup rule pass
# instead of being inserted pre-categorized.
GROCERIES_TOML = """
[[category]]
name = "Groceries"
type = "variable"

[[rule]]
category = "Groceries"
counterparty = "Fake Market"
"""


def _today() -> date:
    return TODAY


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


def _groceries_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text(GROCERIES_TOML, encoding="utf-8")
    return path


def _insert_debit(db_path: Path, *, fingerprint: str, booking_date: str, amount_cents: int) -> None:
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
                'test', 'acc', ?, ?, ?, 'EUR', 'Fake Market', '', NULL, NULL, NULL,
                'raw', ?, 1, NULL
            )
            """,
            (booking_date, booking_date, amount_cents, fingerprint),
        )
        conn.commit()
    finally:
        conn.close()


def _row_cells(html: str, name: str) -> list[str]:
    """Cell texts of the <tr> whose first <td> is exactly `name`."""
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = [cell.strip() for cell in re.findall(r"<td>(.*?)</td>", row, re.S)]
        if cells and cells[0] == name:
            return cells
    raise AssertionError(f"no row found for {name!r}")


def test_nothing_set_links_to_settings_and_has_no_traffic_light(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'href="/settings"' in response.text
    assert 'id="traffic-light"' not in response.text


def test_overdrawn_balance_is_green_at_default_limit_and_red_at_zero(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "-500.00"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                "/settings/balance",
                data={"amount": "-400.00", "as_of": "2026-09-10"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        page = client.get("/")
        assert 'class="light-green"' in page.text
        assert "Overdraft limit: -500.00" in page.text

        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "0"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        page = client.get("/")
        assert 'class="light-red"' in page.text
        assert "Overdraft limit: 0.00" in page.text


def test_not_enough_history_shows_not_enough_data(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "100.00", "as_of": "2026-09-10"})

        page = client.get("/")

    assert "not enough data" in page.text


def test_full_dashboard_row_scoped(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _groceries_categories(tmp_path)

    # Three complete salary cycles of Groceries spending, each entirely
    # within one cycle boundary for salary day 26 (payday moves off a
    # weekend): [05-26,06-25]=93000, [06-26,07-23]=56000, [07-24,08-25]=33000.
    _insert_debit(db_path, fingerprint="g1", booking_date="2026-05-26", amount_cents=-93_000)
    _insert_debit(db_path, fingerprint="g2", booking_date="2026-07-01", amount_cents=-56_000)
    _insert_debit(db_path, fingerprint="g3", booking_date="2026-08-25", amount_cents=-33_000)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "-500.00"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        assert (
            client.post(
                "/recurring",
                follow_redirects=False,
                data={
                    "name": "Rent",
                    "amount": "500.00",
                    "interval_months": "1",
                    "day": "15",
                    "starts_on": "2026-01-15",
                },
            ).status_code
            == 303
        )

        assert (
            client.post(
                "/debts/installments",
                follow_redirects=False,
                data={
                    "name": "Sofa",
                    "total": "1200.00",
                    "rate": "100.00",
                    "interval_months": "1",
                    "first_payment_date": "2026-01-20",
                    "payments_count": "12",
                    "match_field": "counterparty",
                    "match_value": "Sofa Shop",
                },
            ).status_code
            == 303
        )

        assert (
            client.post(
                "/settings/balance",
                data={"amount": "800.00", "as_of": "2026-09-10"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        page = client.get("/").text

        assert "Until next payday (2026-09-25, in 15 days)" in page
        assert "600.00 expected" in page
        assert _row_cells(page, "Rent") == ["Rent", "2026-09-15", "500.00"]
        assert _row_cells(page, "Sofa") == ["Sofa", "2026-09-20", "100.00"]
        assert "210.00–350.00 more" in page
        assert _row_cells(page, "Groceries") == ["Groceries", "280.00"]
        assert (
            'title="25th to 75th percentile of total variable spending in the last 3 complete'
            " salary cycles (at most 6), each scaled to the days from the balance date to"
            ' payday; categories show their median."'
        ) in page
        assert "<p>Balance: 800.00 as of 2026-09-10</p>" in page

        assert 'class="light-green"' in page
        assert "Overdraft limit: -500.00" in page

        assert "Monthly equivalent: 533.33" in page
        fixed_rows = re.findall(r'<table id="fixed-costs">.*?</table>', page, re.S)[0]
        assert _row_cells(fixed_rows, "Rent") == ["Rent", "15", "1", "500.00", "2026-09-15"]
        assert _row_cells(fixed_rows, "Sofa") == ["Sofa", "20", "1", "100.00", "2026-09-20"]

        months_table = re.findall(r'<table id="months">.*?</table>', page, re.S)[0]
        for month in ["2026-09", "2026-10", "2026-11", "2026-12"]:
            assert _row_cells(months_table, month) == [month, "600.00"]
        for month in [
            "2027-01",
            "2027-02",
            "2027-03",
            "2027-04",
            "2027-05",
            "2027-06",
            "2027-07",
            "2027-08",
        ]:
            assert _row_cells(months_table, month) == [month, "500.00"]

        debts_table = re.findall(r'<table id="debts">.*?</table>', page, re.S)[0]
        assert _row_cells(debts_table, "Sofa") == ["Sofa", "1200.00"]
        assert '<p id="debts-total">Total remaining: 1200.00</p>' in page

        assert '<a href="/uncategorized">0</a>' in page

        # 800.00 - 600.00 due - 210.00..350.00 variable = [-150.00, -10.00]: red.
        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "0"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        page = client.get("/").text
        assert 'class="light-red"' in page
        assert "Overdraft limit: 0.00" in page
        assert "<p>Projected: [-150.00, -10.00]</p>" in page
        light = re.findall(r'<div id="traffic-light".*?</div>', page, re.S)[0]
        assert "<p>[-150.00, -10.00]</p>" in light

        # 900.00 gives [-50.00, 90.00]: only the best case stays above 0.00, so yellow.
        client.post("/settings/balance", data={"amount": "900.00", "as_of": "2026-09-10"})
        page = client.get("/").text
        assert 'class="light-yellow"' in page
        assert "<p>Projected: [-50.00, 90.00]</p>" in page
        light = re.findall(r'<div id="traffic-light".*?</div>', page, re.S)[0]
        assert "<p>[-50.00, 90.00]</p>" in light

        # 1000.00 gives [50.00, 190.00]: both cases stay above 0.00, so green.
        client.post("/settings/balance", data={"amount": "1000.00", "as_of": "2026-09-10"})
        page = client.get("/").text
        assert 'class="light-green"' in page
        assert "<p>Projected: [50.00, 190.00]</p>" in page
        light = re.findall(r'<div id="traffic-light".*?</div>', page, re.S)[0]
        assert "<p>[50.00, 190.00]</p>" in light
