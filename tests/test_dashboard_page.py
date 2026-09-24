"""Tests for the dashboard page (SPEC §9): GET / renders load_dashboard's figures.

Seed data for the row-scoped test is picked so the numbers can be checked by
hand: salary day 26 and today 2026-09-10 give payday Friday 2026-09-25 (the
26th is a Saturday) and a window of [2026-09-11, 2026-09-24] (14 days) once
the balance is set as of today. Three Groceries debits, one per complete
salary cycle before that window, give an exact 25th/75th percentile range.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations
from tests.html import cents, fields, records, soup, text

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


def _add_recurring(client, name: str, day: int, starts_on: str, amount: str = "10.00"):
    return client.post(
        "/recurring",
        follow_redirects=False,
        data={
            "name": name,
            "amount": amount,
            "interval_months": "1",
            "day": str(day),
            "starts_on": starts_on,
        },
    )


def _light(page) -> dict[str, int | str]:
    light = page.select_one("#traffic-light")
    return {"light": light["data-light"], **fields(light)}


def _projection(page) -> tuple[int, int]:
    projection = page.select_one("#projection")
    return int(projection["data-worst"]), int(projection["data-best"])


PILL_TEXT = {"green": "On track", "yellow": "Tight", "red": "Overdraft risk"}


def _pill(page) -> str:
    return text(page.select_one("#traffic-light #status-pill"))


def _runway(page) -> tuple[int, int]:
    runway = page.select_one("#runway svg[role=img]")
    return int(runway["data-worst"]), int(runway["data-best"])


def test_nothing_set_links_to_settings_and_has_no_traffic_light(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        response = client.get("/")

    assert response.status_code == 200
    page = soup(response)
    assert page.select_one('#setup-prompt a[href="/settings"]') is not None
    assert page.select_one("#traffic-light") is None
    assert page.select_one("#runway") is None


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

        page = soup(client.get("/"))
        assert page.select_one("#traffic-light")["data-light"] == "green"
        assert cents(page.select_one("#overdraft-limit")) == -50_000

        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "0"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        page = soup(client.get("/"))
        assert page.select_one("#traffic-light")["data-light"] == "red"
        assert cents(page.select_one("#overdraft-limit")) == 0


def test_not_enough_history_shows_not_enough_data(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "100.00", "as_of": "2026-09-10"})

        page = soup(client.get("/"))

    variable_range = page.select_one("#variable-range")
    assert variable_range.select("[data-cents]") == []
    assert text(variable_range) == "not enough data"


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

        page = soup(client.get("/"))

        assert page.select_one("#payday")["datetime"] == "2026-09-25"
        days = page.select_one("#days-to-payday")
        assert days["data-days"] == "15"
        assert text(days) == "in 15 days"
        assert cents(page.select_one("#due-total")) == 60_000
        assert records(page.select_one("#due")) == [
            {"name": "Rent", "date": "2026-09-15", "amount": 50_000},
            {"name": "Sofa", "date": "2026-09-20", "amount": 10_000},
        ]
        variable_range = page.select_one("#variable-range")
        assert fields(variable_range) == {"low": 21_000, "high": 35_000}
        assert records(page.select_one("#variable-breakdown")) == [
            {"category": "Groceries", "median": 28_000}
        ]
        assert variable_range["title"] == (
            "25th to 75th percentile of total variable spending in the last 3 complete"
            " salary cycles (at most 6), each scaled to the days from the balance date to"
            " payday; categories show their median."
        )
        assert fields(page.select_one("#balance")) == {"amount": 80_000, "as_of": "2026-09-10"}
        assert page.select_one("#balance [data-field=amount]").get_text() == "800,00\u00a0€"
        assert text(page.select_one("#payday")) == "25 Sep 2026"

        assert page.select_one("#traffic-light")["data-light"] == "green"
        assert _pill(page) == PILL_TEXT["green"]
        assert cents(page.select_one("#overdraft-limit")) == -50_000
        assert _runway(page) == _projection(page)

        assert cents(page.select_one("#monthly-equivalent")) == 53_333
        assert records(page.select_one("#fixed-costs")) == [
            {
                "name": "Rent",
                "cadence": "monthly · day 15",
                "amount": 50_000,
                "next_due": "2026-09-15",
            },
            {
                "name": "Sofa",
                "cadence": "monthly · day 20",
                "amount": 10_000,
                "next_due": "2026-09-20",
            },
        ]

        months = records(page.select_one("#months"))
        assert [m["month"] for m in months] == [
            "2026-09",
            "2026-10",
            "2026-11",
            "2026-12",
            "2027-01",
            "2027-02",
            "2027-03",
            "2027-04",
            "2027-05",
            "2027-06",
            "2027-07",
            "2027-08",
        ]
        assert [m["total"] for m in months] == [60_000] * 4 + [50_000] * 8
        columns = page.select("#month-columns svg[role=img] rect[data-cents]")
        assert [int(c["data-cents"]) for c in columns] == [60_000] * 4 + [50_000] * 8

        assert records(page.select_one("#debts")) == [{"name": "Sofa", "remaining": 120_000}]
        assert cents(page.select_one("#debts-total")) == 120_000

        assert page.select_one("#uncategorized-callout") is None

        # 800.00 - 600.00 due - 210.00..350.00 variable = [-150.00, -10.00]: red.
        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "0"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        page = soup(client.get("/"))
        assert _light(page) == {"light": "red", "worst": -15_000, "best": -1_000, "limit": 0}
        assert _projection(page) == (-15_000, -1_000)
        assert _pill(page) == PILL_TEXT["red"]
        assert _runway(page) == (-15_000, -1_000)

        # 900.00 gives [-50.00, 90.00]: only the best case stays above 0.00, so yellow.
        client.post("/settings/balance", data={"amount": "900.00", "as_of": "2026-09-10"})
        page = soup(client.get("/"))
        assert _light(page) == {"light": "yellow", "worst": -5_000, "best": 9_000, "limit": 0}
        assert _projection(page) == (-5_000, 9_000)
        assert _pill(page) == PILL_TEXT["yellow"]
        assert _runway(page) == (-5_000, 9_000)

        # 1000.00 gives [50.00, 190.00]: both cases stay above 0.00, so green.
        client.post("/settings/balance", data={"amount": "1000.00", "as_of": "2026-09-10"})
        page = soup(client.get("/"))
        assert _light(page) == {"light": "green", "worst": 5_000, "best": 19_000, "limit": 0}
        assert _projection(page) == (5_000, 19_000)
        assert _pill(page) == PILL_TEXT["green"]
        assert _runway(page) == (5_000, 19_000)


def test_uncategorized_callout_links_to_the_page_when_count_is_above_zero(tmp_path):
    db_path = tmp_path / "t.db"
    # An empty taxonomy leaves the seeded debit uncategorized.
    categories_path = _empty_categories(tmp_path)
    _insert_debit(db_path, fingerprint="u1", booking_date="2026-09-01", amount_cents=-1_000)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        page = soup(client.get("/"))

    callout_link = page.select_one('#uncategorized-callout a[href="/uncategorized"]')
    assert int(text(callout_link)) == 1


def test_due_list_shows_first_eight_and_rest_in_a_details(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "1000.00", "as_of": "2026-09-10"})
        # 10 monthly bills, one per day 11..20, all land inside the payday window
        # [2026-09-11, 2026-09-24].
        for day in range(11, 21):
            assert (
                _add_recurring(client, f"Bill{day}", day, f"2026-01-{day:02d}").status_code == 303
            )

        page = soup(client.get("/"))

    due_rows = records(page.select_one("#due"))
    assert [row["date"] for row in due_rows] == [f"2026-09-{d:02d}" for d in range(11, 19)]

    more = page.select_one("#due-more")
    assert text(more.select_one("summary")) == "Show all 10"
    more_rows = records(more)
    assert [row["date"] for row in more_rows] == ["2026-09-19", "2026-09-20"]

    assert cents(page.select_one("#due-total")) == 10 * 1_000


def test_due_list_has_no_details_at_eight_rows_or_fewer(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "1000.00", "as_of": "2026-09-10"})
        for day in range(11, 14):
            assert (
                _add_recurring(client, f"Bill{day}", day, f"2026-01-{day:02d}").status_code == 303
            )

        page = soup(client.get("/"))

    assert len(records(page.select_one("#due"))) == 3
    assert page.select_one("#due-more") is None


@pytest.mark.parametrize(
    ("hero_today", "salary_day", "expected_days", "expected_text"),
    [
        # Sep 25 2026 is a Friday (Sep 26 is the Saturday used elsewhere in
        # this file), so salary day 25 lands exactly one day after "today".
        (date(2026, 9, 24), 25, 1, "in 1 day"),
        (date(2026, 9, 10), 26, 15, "in 15 days"),
        # 0/"today" is covered at the filter level (test_display.py): payday
        # is always strictly after `today` (see payday.next_payday), so the
        # dashboard itself can never show a 0-day gap.
    ],
)
def test_hero_shows_days_until_text(tmp_path, hero_today, salary_day, expected_days, expected_text):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(
        create_app(db_path, categories_path=categories_path, today=lambda: hero_today)
    ) as client:
        client.post("/settings", data={"salary_day": str(salary_day), "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "100.00", "as_of": hero_today.isoformat()})

        page = soup(client.get("/"))

    days = page.select_one("#days-to-payday")
    assert days["data-days"] == str(expected_days)
    assert text(days) == expected_text
