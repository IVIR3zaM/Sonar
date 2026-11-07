"""Monthly ledger keeps paid and expected amounts visible in their equation."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.web.app import create_app
from tests.html import cents, fields, soup, text
from tests.seed import seed
from tests.web.test_monthly_page import GROUPS_TOML, _insert


@pytest.fixture
def ledger_client(tmp_path, request):
    db_path = tmp_path / "ledger.db"
    seed(
        db_path,
        GROUPS_TOML
        + """
[[category]]
name = "Salary"
type = "income"
[[category]]
name = "Child Allowance"
type = "income"
[[rule]]
category = "Salary"
counterparty = "Fake Employer"
[[rule]]
category = "Child Allowance"
counterparty = "Fake Allowance"
""",
    )
    for index, (name, amount) in enumerate(
        [
            ("Fake Employer", 450_000),
            ("Fake Allowance", 50_000),
            ("Fake Landlord", -100_000),
            ("Fake Market", -3_000),
            ("Fake Cafe", -2_000),
            ("Fake Unknown", -1_000),
            ("Fake Own Account", -10_000),
        ]
    ):
        _insert(
            db_path,
            fingerprint=f"ledger-{index}",
            booking_date="2026-09-05",
            amount_cents=amount,
            counterparty=name,
        )
    today = getattr(request, "param", date(2026, 10, 15))
    with TestClient(create_app(db_path, today=lambda: today)) as client:
        yield client


def test_past_ledger_order_amounts_and_income_breakdown(ledger_client):
    page = soup(ledger_client.get("/monthly?month=2026-09"))
    ledger = page.select_one("#monthly-ledger")
    hooks = [
        "net-income",
        "group-fixed",
        "group-lights-on",
        "possible-residual",
        "group-occasional",
        "group-uncategorized",
        "residual-income",
    ]
    assert [el["id"] for el in ledger.select("[id]") if el["id"] in hooks] == hooks
    assert [cents(page.select_one(f"#{hook}")) for hook in hooks] == [
        500_000,
        -100_000,
        -3_000,
        397_000,
        -2_000,
        -1_000,
        394_000,
    ]
    assert [
        (el["data-category"], cents(el), int(el["data-upcoming-cents"]))
        for el in ledger.select('[data-part="income-category"]')
    ] == [("Salary", 450_000, 0), ("Child Allowance", 50_000, 0)]
    assert cents(page.select_one("#month-total")) == -106_000
    assert page.select_one("#not-counted #stat-transfer #transfers-net") is not None
    assert text(page.select_one("#not-counted #payments-count")) == "Payments 5"
    assert page.select_one("#forecast-note") is None


@pytest.mark.parametrize("ledger_client", [date(2026, 9, 15)], indirect=True)
def test_current_ledger_includes_upcoming_and_forecast_window(ledger_client):
    assert ledger_client.put(
        "/api/settings", json={"salary_day": 1, "overdraft_limit_cents": 0}
    ).is_success
    assert ledger_client.post(
        "/api/settings/balance", json={"amount_cents": 200_000, "as_of": "2026-09-15"}
    ).is_success
    response = ledger_client.post(
        "/api/recurring",
        json={
            "name": "Future rent",
            "amount_cents": 20_000,
            "interval_months": 1,
            "day": 20,
            "starts_on": "2026-09-01",
            "description": "",
            "category": "Housing",
        },
    )
    assert response.is_success, response.text
    page = soup(ledger_client.get("/monthly?month=2026-09"))
    fixed = page.select_one("#group-fixed")
    assert cents(fixed) == -120_000
    assert fixed["data-upcoming-cents"] == "-20000"
    assert "paid +" in text(page.select_one("#stat-fixed"))
    assert cents(page.select_one("#possible-residual")) == 377_000
    assert cents(page.select_one("#residual-income")) == 374_000
    assert page.select_one("#month-total")["data-upcoming-cents"] == "-20000"
    assert fields(page.select_one("#forecast-note")) == {
        "from": "2026-09-16",
        "to": "2026-09-30",
    }


def test_zero_income_omits_income_and_residuals_and_keeps_group_links(ledger_client):
    page = soup(ledger_client.get("/monthly?month=2026-08&group=fixed"))
    assert page.select_one("#monthly-ledger") is not None
    assert not page.select("#net-income, #possible-residual, #residual-income")
    assert page.select_one("#group-uncategorized") is None
    link = page.select_one("#stat-fixed")
    assert link["aria-current"] == "true"
    assert link["href"] == "/monthly?month=2026-08"
    assert link["hx-boost"] == "true"
