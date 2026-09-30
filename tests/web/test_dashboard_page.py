"""Tests for the dashboard page (SPEC §9): GET / renders load_dashboard's figures.

Seed data for the row-scoped test is picked so the numbers can be checked by
hand: salary day 26 and today 2026-09-10 give payday Friday 2026-09-25 (the
26th is a Saturday) and a window of [2026-09-11, 2026-09-24] (14 days) once
the balance is set as of today. Three Groceries debits, one per complete
salary month before that window, give daily averages of 30.00, 20.00 and
10.00 over 31, 28 and 33 days, so the lights-on range is exact.
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.web.app import create_app
from tests.html import cents, fields, records, soup, text
from tests.seed import seed

TODAY = date(2026, 9, 10)

# Groceries is `lights_on` and matches the fake counterparty "Fake Market", so
# the seeded debits below are categorized by the app's own startup rule pass
# instead of being inserted pre-categorized. Dining is `occasional`.
GROCERIES_TOML = """
[[category]]
name = "Groceries"
type = "lights_on"

[[category]]
name = "Dining"
type = "occasional"

[[rule]]
category = "Groceries"
counterparty = "Fake Market"
"""


def _today() -> date:
    return TODAY


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
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        response = client.get("/")

    assert response.status_code == 200
    page = soup(response)
    assert page.select_one('#setup-prompt a[href="/settings"]') is not None
    assert page.select_one("#traffic-light") is None
    assert page.select_one("#runway") is None


def test_overdrawn_balance_is_green_at_default_limit_and_red_at_zero(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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


def test_runway_legend_shows_the_values(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "-400.00", "as_of": "2026-09-10"})
        page = soup(client.get("/"))

    worst, best = _projection(page)
    overdraft = page.select_one("#runway [data-legend=overdraft]")
    projected = page.select_one("#runway [data-legend=projected]")
    balance = page.select_one("#runway [data-legend=balance]")
    assert text(overdraft).startswith("Overdraft zone down to")
    assert cents(overdraft) == -50_000
    assert text(projected).startswith("Projected at payday")
    assert [int(a["data-cents"]) for a in projected.select("[data-cents]")] == [worst, best]
    assert text(balance).startswith("Balance on")
    assert balance.select_one("time[datetime]")["datetime"] == "2026-09-10"
    assert cents(balance) == -40_000
    ids = [el["id"] for el in page.select("[id]")]
    assert len(ids) == len(set(ids))


def test_not_enough_history_shows_not_enough_data(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, GROCERIES_TOML)

    with TestClient(create_app(db_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "100.00", "as_of": "2026-09-10"})

        page = soup(client.get("/"))

    expected = page.select_one("#lights-on-card #lights-on-expected")
    assert expected.select("[data-cents]") == []
    assert text(expected) == "not enough data"


def test_no_lights_on_category_links_to_the_categories_page(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "100.00", "as_of": "2026-09-10"})

        page = soup(client.get("/"))

    assert page.select_one('#lights-on-card #lights-on-empty a[href="/categories"]') is not None
    assert page.select_one("#lights-on-expected") is None
    assert _projection(page) == (10_000, 10_000)


def test_full_dashboard_row_scoped(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, GROCERIES_TOML)

    # Three complete salary cycles of Groceries spending, each entirely
    # within one cycle boundary for salary day 26 (payday moves off a
    # weekend): [05-26,06-25]=93000, [06-26,07-23]=56000, [07-24,08-25]=33000.
    _insert_debit(db_path, fingerprint="g1", booking_date="2026-05-26", amount_cents=-93_000)
    _insert_debit(db_path, fingerprint="g2", booking_date="2026-07-01", amount_cents=-56_000)
    _insert_debit(db_path, fingerprint="g3", booking_date="2026-08-25", amount_cents=-33_000)

    with TestClient(create_app(db_path, today=_today)) as client:
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
        # Expected: 182,000 cents over 92 days x 14 days = 27,695.65 -> 27,696.
        # Range: the lowest and highest daily average (1,000, 3,000) x 14 days.
        card = page.select_one("#lights-on-card")
        assert fields(card.select_one("#lights-on-forecast")) == {
            "expected": 27_696,
            "low": 14_000,
            "high": 42_000,
        }
        assert records(card.select_one("#lights-on-breakdown")) == [
            {"category": "Groceries", "amount": 27_696}
        ]
        method = card.select_one("#lights-on-expected")["title"]
        assert "Groceries" in method
        assert "3 complete months" in method
        assert "14 days" in method
        assert card.select_one('a[href="/lights-on"]') is not None
        occasional = card.select_one("#occasional-note")
        assert "Dining" in text(occasional)
        assert occasional.select_one('a[href="/monthly"]') is not None
        # 800.00 - 600.00 due - 276.96 expected = -76.96: inside the -500.00
        # overdraft, 423.04 before the limit.
        shortfall = page.select_one("#shortfall")
        assert cents(shortfall) == -7_696
        assert shortfall["data-headroom"] == "42304"
        assert text(shortfall) == "About 76,96 € into your overdraft, 423,04 € before the limit"
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

        # 700.00 - 600.00 due - 140.00..420.00 lights-on = [-320.00, -40.00]: red.
        client.post("/settings/balance", data={"amount": "700.00", "as_of": "2026-09-10"})
        assert (
            client.post(
                "/settings",
                data={"salary_day": "26", "overdraft_limit": "0"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        page = soup(client.get("/"))
        assert _light(page) == {"light": "red", "worst": -32_000, "best": -4_000, "limit": 0}
        assert _projection(page) == (-32_000, -4_000)
        assert _pill(page) == PILL_TEXT["red"]
        assert _runway(page) == (-32_000, -4_000)
        # 700.00 - 600.00 - 276.96 = -176.96, past the 0.00 limit.
        shortfall = page.select_one("#shortfall")
        assert shortfall["data-headroom"] == "-17696"
        assert text(shortfall) == "About 176,96 € past your overdraft limit"

        # 800.00 gives [-220.00, 60.00]: only the best case stays above 0.00, so yellow.
        client.post("/settings/balance", data={"amount": "800.00", "as_of": "2026-09-10"})
        page = soup(client.get("/"))
        assert _light(page) == {"light": "yellow", "worst": -22_000, "best": 6_000, "limit": 0}
        assert _projection(page) == (-22_000, 6_000)
        assert _pill(page) == PILL_TEXT["yellow"]
        assert _runway(page) == (-22_000, 6_000)

        # 1100.00 gives [80.00, 360.00]: both cases stay above 0.00, so green,
        # and 1100.00 - 600.00 - 276.96 leaves 223.04 to spare.
        client.post("/settings/balance", data={"amount": "1100.00", "as_of": "2026-09-10"})
        page = soup(client.get("/"))
        assert _light(page) == {"light": "green", "worst": 8_000, "best": 36_000, "limit": 0}
        assert _projection(page) == (8_000, 36_000)
        assert _pill(page) == PILL_TEXT["green"]
        assert _runway(page) == (8_000, 36_000)
        assert cents(page.select_one("#shortfall")) == 22_304
        assert text(page.select_one("#shortfall")) == "About 223,04 € to spare"


def test_uncategorized_callout_links_to_the_page_when_count_is_above_zero(tmp_path):
    db_path = tmp_path / "t.db"
    # An empty taxonomy leaves the seeded debit uncategorized.
    seed(db_path)
    _insert_debit(db_path, fingerprint="u1", booking_date="2026-09-01", amount_cents=-1_000)

    with TestClient(create_app(db_path, today=_today)) as client:
        page = soup(client.get("/"))

    callout_link = page.select_one('#uncategorized-callout a[href="/uncategorized"]')
    assert int(text(callout_link)) == 1


def test_due_list_shows_first_eight_and_rest_in_a_details(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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
    seed(db_path)

    with TestClient(create_app(db_path, today=lambda: hero_today)) as client:
        client.post("/settings", data={"salary_day": str(salary_day), "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "100.00", "as_of": hero_today.isoformat()})

        page = soup(client.get("/"))

    days = page.select_one("#days-to-payday")
    assert days["data-days"] == str(expected_days)
    assert text(days) == expected_text


def test_dashboard_and_lights_on_page_learn_from_the_same_months(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, GROCERIES_TOML)
    # Weekly Groceries debits from March to 08-20, a bit more each month. The
    # balance is dated 09-10, so the salary month [07-24, 08-25] ends before
    # the balance date but after the last booking: only partly known.
    day = date(2026, 3, 1)
    while day <= date(2026, 8, 20):
        _insert_debit(
            db_path,
            fingerprint=f"w{day.isoformat()}",
            booking_date=day.isoformat(),
            amount_cents=-(2_000 + 300 * day.month),
        )
        day += timedelta(days=7)

    with TestClient(create_app(db_path, today=_today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "800.00", "as_of": "2026-09-10"})
        dashboard = soup(client.get("/"))
        lights = soup(client.get("/lights-on"))

    basis = dashboard.select_one("#lights-on-card #lights-on-basis")
    assert basis is not None
    daily = cents(basis.select_one('[data-field="daily"]'))
    days = int(basis.select_one('[data-field="days"]')["data-days"])
    assert days == 14
    assert daily == cents(lights.select_one("#daily-average"))

    used = lights.select('#lights-on-table [data-row][data-used="true"]')
    assert len(used) == 3
    assert (
        basis.select_one('[data-field="from"] time')["datetime"]
        == (used[0].select_one("[data-field=start] time")["datetime"])
    )
    assert (
        basis.select_one('[data-field="to"] time')["datetime"]
        == (used[-1].select_one("[data-field=end] time")["datetime"])
    )
    assert used[-1].select_one("[data-field=end] time")["datetime"] == "2026-07-23"

    forecast = fields(dashboard.select_one("#lights-on-forecast"))
    assert abs(cents(lights.select_one("#daily-low")) * days - forecast["low"]) <= days
    assert abs(cents(lights.select_one("#daily-high")) * days - forecast["high"]) <= days


def _page_with_balance(tmp_path, *, today: date, as_of: date):
    db_path = tmp_path / "t.db"
    seed(db_path)
    with TestClient(create_app(db_path, today=lambda: today)) as client:
        client.post("/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"})
        client.post("/settings/balance", data={"amount": "100.00", "as_of": as_of.isoformat()})
        return soup(client.get("/"))


def test_hero_shows_the_date_the_estimate_starts_from(tmp_path):
    page = _page_with_balance(tmp_path, today=date(2026, 9, 11), as_of=date(2026, 9, 10))

    estimated = page.select_one("#hero #estimated-from")
    assert text(estimated).startswith("Estimated from")
    assert estimated.select_one("time[datetime]")["datetime"] == "2026-09-10"
    assert page.select_one("#stale-data") is None


def test_passed_payday_shows_a_stale_data_notice(tmp_path):
    page = _page_with_balance(tmp_path, today=date(2026, 9, 30), as_of=date(2026, 9, 10))

    notice = page.select_one("#stale-data")
    assert notice["role"] == "status"
    assert notice.select_one("time[datetime]")["datetime"] == "2026-09-25"
    assert notice.select_one("a")["href"] == "/import"
    days = page.select_one("#days-to-payday")
    assert int(days["data-days"]) < 0
    assert text(days) == "5 days ago"
