"""Bare minimum dashboard card (SPEC §13)."""

import pytest
from fastapi.testclient import TestClient

from sonar.cashflow.service import load_dashboard
from sonar.db import connect
from sonar.web.app import create_app
from tests.html import cents, fields, records, soup, text
from tests.seed import seed
from tests.web.test_dashboard_page import (
    GROCERIES_TOML,
    SALARY_TOML,
    TODAY,
    _insert_debit,
    _insert_salary,
    _today,
)


def _seed(db_path, *, income=True, lights=True):
    seed(db_path, (SALARY_TOML if income else "") + (GROCERIES_TOML if lights else ""))
    if income:
        _insert_salary(db_path)
    if lights:
        for month in (6, 7, 8):
            _insert_debit(
                db_path,
                fingerprint=f"groceries-{month}",
                booking_date=f"2026-{month:02d}-01",
                amount_cents=-30_000,
            )


def _settings(client):
    assert (
        client.post(
            "/settings", data={"salary_day": "26", "overdraft_limit": "-500.00"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("ending_debt", [True, False])
@pytest.mark.parametrize("rent", ["500.00", "5000.00"])
def test_bare_minimum_matches_dashboard(tmp_path, ending_debt, rent):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    for month in (6, 7, 8):
        _insert_debit(
            db_path,
            fingerprint=f"extras-{month}",
            booking_date=f"2026-{month:02d}-05",
            amount_cents=-20_000,
            counterparty="Restaurant",
        )
    with TestClient(create_app(db_path, today=_today)) as client:
        _settings(client)
        assert (
            client.post(
                "/api/categories", json={"name": "Extras", "group": "occasional", "debt": False}
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/rules",
                json={"category": "Extras", "counterparty": "Restaurant", "position": 1},
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/recurring",
                data={
                    "name": "Rent",
                    "amount": rent,
                    "interval_months": "1",
                    "day": "15",
                    "starts_on": "2026-01-15",
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        if ending_debt:
            assert (
                client.post(
                    "/debts/installments",
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
                    follow_redirects=False,
                ).status_code
                == 303
            )
        page = soup(client.get("/"))
        conn = connect(db_path)
        try:
            dashboard = load_dashboard(
                conn,
                {
                    "Salary": "income",
                    "Groceries": "lights_on",
                    "Dining": "occasional",
                    "Extras": "occasional",
                },
                TODAY,
            )
        finally:
            conn.close()

    minimum = dashboard.bare_minimum
    assert minimum is not None
    assert minimum.occasional_cents == 20_000
    assert (minimum.residual_cents < 0) == (rent == "5000.00")
    assert (minimum.occasional_margin_cents < 0) == (rent == "5000.00")
    equation = page.select_one("#bare-minimum-equation")
    assert equation is not None
    assert fields(equation) == {
        "income": minimum.income_cents,
        "total": minimum.total_cents,
        "cycle": fields(page.select_one("#bare-minimum"))["cycle"],
        "residual": minimum.residual_cents,
    }
    summary = page.select_one("#bare-minimum-summary")
    assert int(summary["data-residual"]) == minimum.residual_cents
    assert int(summary["data-margin"]) == minimum.occasional_margin_cents
    assert fields(summary) == {
        "residual": minimum.residual_cents,
        "occasional": minimum.occasional_cents,
        "margin": minimum.occasional_margin_cents,
    }
    assert ("shortfall" in text(summary)) == (minimum.residual_cents < 0)
    assert ("below" in text(summary)) == (minimum.occasional_margin_cents < 0)
    assert [
        el["id"]
        for el in page.select(
            "#bare-minimum-equation, #bare-minimum-bar, #bare-minimum-summary, "
            "#bare-minimum-fixed, #bare-minimum-lights, #bare-minimum-chart, "
            "#bare-minimum-cycles"
        )
    ] == [
        "bare-minimum-equation",
        "bare-minimum-bar",
        "bare-minimum-summary",
        "bare-minimum-fixed",
        "bare-minimum-lights",
        "bare-minimum-chart",
        "bare-minimum-cycles",
    ]
    assert {
        part["data-part"]: cents(part) for part in page.select("#bare-minimum-bar [data-cents]")
    } == {
        "fixed": minimum.cycle.fixed_cents,
        "lights": minimum.cycle.lights_on_cents,
        "income": minimum.income_cents,
    }
    gap = page.select_one("#bare-minimum-gap-note")
    assert fields(gap) == {
        "monthly": dashboard.fixed_costs.monthly_equivalent_cents,
        "cycle": minimum.cycle.fixed_cents,
    }
    bars = page.select("#bare-minimum-chart rect[data-cents]")
    assert [cents(bar) for bar in bars] == [cycle.residual_cents for cycle in minimum.cycles]
    for bar, cycle in zip(bars, minimum.cycles, strict=True):
        assert bar.has_attr("data-max") == (cycle.residual_cents == minimum.residual_cents)
    table_details = page.select_one("#bare-minimum-cycles").find_parent("details")
    assert table_details is not None and not table_details.has_attr("open")
    assert text(table_details.select_one("summary")) == "Show as table"
    assert [el["id"] for el in page.select("#lights-on-card, #bare-minimum-card, #fixed-card")] == [
        "lights-on-card",
        "bare-minimum-card",
        "fixed-card",
    ]
    for hook, expected in {
        "bare-minimum": minimum.total_cents,
        "bare-minimum-fixed": minimum.cycle.fixed_cents,
        "bare-minimum-lights": minimum.cycle.lights_on_cents,
        "bare-minimum-income": minimum.income_cents,
        "bare-minimum-residual": minimum.residual_cents,
    }.items():
        assert cents(page.select_one(f"#{hook}")) == expected
    assert fields(page.select_one("#bare-minimum")) == {
        "cycle": page.select_one("#bare-minimum-cycles [data-max] [data-field=cycle]").get_text()
    }
    lights = page.select_one("#bare-minimum-lights")
    assert (
        cents(lights.select_one("[data-field=daily]"))
        == minimum.cycle.lights_on_cents // minimum.cycle.days
    )
    assert int(lights.select_one("[data-days]")["data-days"]) == minimum.cycle.days
    share = page.select_one("#bare-minimum-debt-share")
    assert int(share["data-percent"]) == minimum.debt_share_percent
    assert cents(share) == minimum.debt_cents
    assert share.find_parent(id="bare-minimum-fixed") is not None
    assert "debt" in text(share).lower()
    occasional = page.select_one("#bare-minimum-occasional")
    assert int(occasional["data-margin"]) == minimum.occasional_margin_cents
    assert cents(occasional) == minimum.occasional_cents
    rows = page.select("#bare-minimum-cycles [data-row]")
    assert len(rows) == 6
    assert len(page.select("#bare-minimum-cycles [data-max]")) == 1
    for row, cycle in zip(rows, minimum.cycles, strict=True):
        assert fields(row) == {
            "cycle": fields(row)["cycle"],
            "fixed": cycle.fixed_cents,
            "lights": cycle.lights_on_cents,
            "need": cycle.need_cents,
            "residual": cycle.residual_cents,
        }
        assert [
            row.select_one("[data-field=cycle]")[key] for key in ("data-start", "data-end")
        ] == [
            cycle.start.isoformat(),
            cycle.end.isoformat(),
        ]
    if ending_debt:
        assert minimum.drops
        assert records(page.select_one("#bare-minimum-drops")) == [
            {
                "name": drop.name,
                "kind": drop.kind,
                "end_date": drop.end_date.isoformat(),
                "rate": drop.rate_cents,
            }
            for drop in minimum.drops
        ]
    else:
        assert page.select_one("#bare-minimum-no-drops") is None
        assert page.select_one("#bare-minimum-drops") is None
        assert "Upcoming debt endings" not in text(page.select_one("#bare-minimum-card"))


@pytest.mark.parametrize(
    "reason,link",
    [("salary_day", "/settings"), ("income", "/categories"), ("lights_on", "/lights-on")],
)
def test_bare_minimum_hint(tmp_path, reason, link):
    db_path = tmp_path / "test.db"
    if reason == "lights_on":
        seed(db_path, SALARY_TOML + GROCERIES_TOML)
        _insert_debit(
            db_path,
            fingerprint="salary",
            booking_date="2026-08-15",
            amount_cents=200_000,
            counterparty="Employer",
        )
        _insert_debit(
            db_path,
            fingerprint="recent",
            booking_date="2026-09-10",
            amount_cents=-100,
            counterparty="Other",
        )
    else:
        _seed(db_path, income=reason != "income")
    with TestClient(create_app(db_path, today=_today)) as client:
        if reason != "salary_day":
            _settings(client)
        client.post("/settings/balance", data={"amount": "100.00", "as_of": "2026-09-10"})
        page = soup(client.get("/"))
    hint = page.select_one("#bare-minimum-hint")
    assert hint["data-reason"] == reason
    assert hint.select_one(f'a[href="{link}"]') is not None
    assert page.select_one("#bare-minimum") is None
