"""Fixed cost composition inside the Bare minimum card (SPEC §13)."""

import pytest
from fastapi.testclient import TestClient

from sonar.cashflow.service import load_dashboard
from sonar.db import connect
from sonar.web.app import create_app
from tests.html import cents, fields, soup
from tests.web.test_dashboard_bare_minimum import _seed, _settings
from tests.web.test_dashboard_page import TODAY, _today


@pytest.mark.parametrize("hint", [True, False])
def test_fixed_breakdown_matches_dashboard(tmp_path, hint):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    with TestClient(create_app(db_path, today=_today)) as client:
        if not hint:
            _settings(client)
        for name, amount in (("Rent", "500.00"), ("Insurance", "40.00")):
            assert (
                client.post(
                    "/recurring",
                    data={
                        "name": name,
                        "amount": amount,
                        "interval_months": "1",
                        "day": "15",
                        "starts_on": "2026-01-15",
                    },
                    follow_redirects=False,
                ).status_code
                == 303
            )
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
            conn, {"Salary": "income", "Groceries": "lights_on", "Dining": "occasional"}, TODAY
        )
    finally:
        conn.close()

    assert bool(page.select_one("#bare-minimum-hint")) == hint
    assert bool(page.select_one("#bare-minimum")) != hint
    breakdown = dashboard.fixed_breakdown
    assert breakdown.count == 3
    assert len(breakdown.groups) > 1
    section = page.select_one("#bare-minimum-card #fixed-breakdown")
    assert section is not None
    assert int(section["data-total"]) == breakdown.total_cents
    assert int(section["data-count"]) == breakdown.count
    assert cents(section.select_one("[data-field=total]")) == breakdown.total_cents
    assert fields(section.select_one("[data-header]")) == {
        "total": breakdown.total_cents,
        "count": str(breakdown.count),
    }
    groups = section.select("[data-group]")
    assert len(groups) == len(breakdown.groups)
    for group, expected in zip(groups, breakdown.groups, strict=True):
        assert not group.has_attr("open")
        assert fields(group.select_one("[data-summary]")) == {
            "name": expected.name,
            "share": f"{expected.share_percent}%",
            "total": expected.total_cents,
        }
        assert int(group.select_one("[data-percent]")["data-percent"]) == expected.share_percent
        assert [fields(payment) for payment in group.select("[data-payment]")] == [
            {"name": payment.name, "amount": payment.monthly_cents} for payment in expected.payments
        ]


def test_fixed_breakdown_absent_without_fixed_payments(tmp_path):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    with TestClient(create_app(db_path, today=_today)) as client:
        _settings(client)
        assert soup(client.get("/")).select_one("#fixed-breakdown") is None
