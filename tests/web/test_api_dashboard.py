"""Tests for GET /api/dashboard (SPEC §9, §13): the dashboard as JSON."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.cashflow.service import load_dashboard
from sonar.categorization.store import load_stored_taxonomy
from sonar.db import connect
from sonar.debts.model import Loan, MatchRule
from sonar.debts.store import add_debt
from sonar.web.app import create_app
from tests.seed import seed

TODAY = date(2026, 9, 10)


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "t.db"
    seed(db_path)
    client = TestClient(create_app(db_path, today=lambda: TODAY))
    client.db_path = db_path
    return client


def _expected_board(db_path: Path):
    conn = connect(db_path)
    try:
        return load_dashboard(conn, load_stored_taxonomy(conn).categories, TODAY)
    finally:
        conn.close()


def test_without_a_salary_day_the_forecast_keys_are_null(tmp_path):
    with _client(tmp_path) as client:
        body = client.get("/api/dashboard").json()

    assert body["salary_day"] is None
    for key in ("payday", "days_to_payday", "window_days", "expected_cents", "projection", "light"):
        assert body[key] is None
    assert body["balance"] is None
    assert body["due"] == []
    assert body["debts"] == []


def test_with_salary_day_balance_and_manual_payment_matches_load_dashboard(tmp_path):
    with _client(tmp_path) as client:
        client.put("/api/settings", json={"salary_day": 26})
        client.post("/api/settings/balance", json={"amount_cents": 100_000, "as_of": "2026-09-10"})
        client.post(
            "/api/recurring",
            json={
                "name": "Rent",
                "amount_cents": 50_000,
                "interval_months": 1,
                "day": 15,
                "starts_on": "2026-01-01",
            },
        )
        response = client.get("/api/dashboard")
        board = _expected_board(client.db_path)

    body = response.json()
    assert response.status_code == 200
    assert body["payday"] == "2026-09-25" == board.payday.isoformat()
    assert body["balance"] == {"as_of": "2026-09-10", "amount_cents": 100_000, "source": "manual"}
    assert body["expected_cents"] == board.expected_cents == 50_000
    assert body["due"] == [{"name": "Rent", "due_date": "2026-09-15", "amount_cents": 50_000}]
    assert body["due_total_cents"] == board.due_total_cents


def test_debts_are_objects_with_name_and_remaining_cents(tmp_path):
    with _client(tmp_path) as client:
        conn = sqlite3.connect(client.db_path)
        try:
            add_debt(
                conn,
                Loan(
                    name="Car loan",
                    balance_cents=1_000_000,
                    balance_as_of=date(2026, 9, 1),
                    rate_cents=100_000,
                    interest_bp=None,
                    match=MatchRule("counterparty", "Fake Bank"),
                ),
            )
        finally:
            conn.close()
        body = client.get("/api/dashboard").json()

    assert [d["name"] for d in body["debts"]] == ["Car loan"]
    assert set(body["debts"][0]) == {"name", "remaining_cents"}
    assert body["debts_total_cents"] == sum(d["remaining_cents"] for d in body["debts"])
