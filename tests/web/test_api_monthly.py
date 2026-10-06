"""Tests for GET /api/monthly (SPEC §13 Pages): the Monthly page as JSON."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.auth.settings import AuthSettings
from sonar.cashflow.monthly import UNCATEGORIZED
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.web.app import create_app
from tests.seed import seed
from tests.web.fake_google import FakeGoogle

TOML = """
[[category]]
name = "Groceries"
type = "lights_on"

[[category]]
name = "Own transfers"
type = "transfer"

[[rule]]
category = "Groceries"
counterparty = "Fake Market"

[[rule]]
category = "Own transfers"
counterparty = "Own Account"
"""

# (counterparty, booking date, cents)
ROWS = [
    ("Fake Market", "2026-07-03", -1000),
    ("Fake Market", "2026-08-03", -2000),
    ("Unknown Ltd", "2026-08-10", -500),
    ("Own Account", "2026-08-12", -9000),
    ("Employer", "2026-08-25", 300000),
]


def _insert_all(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        for index, (counterparty, booking, cents) in enumerate(ROWS):
            conn.execute(
                """
                INSERT INTO transactions (
                    source, account, booking_date, value_date, amount_cents, currency,
                    counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                    fingerprint, occurrence, category
                ) VALUES (
                    'test', 'acc', ?, ?, ?, 'EUR', ?, 'p', NULL, NULL, NULL, 'raw', ?, 1, NULL
                )
                """,
                (booking, booking, cents, counterparty, f"fp{index}"),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, TOML)
    _insert_all(db_path)
    app = create_app(db_path, today=lambda: date(2026, 11, 5))
    with TestClient(app) as client:
        # The rules categorize the seeded rows.
        client.post("/api/reapply")
        yield client


def test_default_month_is_the_latest_with_payments(client):
    body = client.get("/api/monthly").json()

    assert (body["month"], body["start"], body["end"]) == ("2026-08-01", "2026-08-01", "2026-08-31")
    assert body["salary_months"] is False
    assert body["months"] == ["2026-08-01", "2026-07-01"]
    assert (body["older"], body["newer"]) == ("2026-07-01", None)
    assert body["spent_cents"] == -2500
    assert body["transfers_net_cents"] == -9000
    assert body["groups"]["lights_on_cents"] == -2000
    assert body["groups"]["uncategorized_cents"] == -500
    assert [(c["category"], c["total_cents"], c["count"]) for c in body["by_category"]] == [
        ("Groceries", -2000, 1),
        (None, -500, 1),
    ]
    assert [(c["category"], c["total_cents"]) for c in body["transfer_totals"]] == [
        ("Own transfers", -9000)
    ]
    assert [p["counterparty"] for p in body["payments"]] == [
        "Own Account",
        "Unknown Ltd",
        "Fake Market",
    ]
    assert body["payments"][2]["category"] == "Groceries"
    assert "raw_row" not in body["payments"][0]


def test_chosen_month_selects_its_period_and_neighbours(client):
    body = client.get("/api/monthly", params={"month": "2026-07"}).json()

    assert (body["month"], body["older"], body["newer"]) == ("2026-07-01", None, "2026-08-01")
    assert body["spent_cents"] == -1000
    assert [p["counterparty"] for p in body["payments"]] == ["Fake Market"]


def test_category_narrows_only_the_payments(client):
    body = client.get("/api/monthly", params={"category": "Groceries"}).json()

    assert [p["counterparty"] for p in body["payments"]] == ["Fake Market"]
    assert body["spent_cents"] == -2500
    assert len(body["by_category"]) == 2


def test_uncategorized_key_narrows_to_uncategorized_payments(client):
    body = client.get("/api/monthly", params={"category": UNCATEGORIZED}).json()

    assert [p["counterparty"] for p in body["payments"]] == ["Unknown Ltd"]


def test_bad_month_answers_400_naming_the_field(client):
    response = client.get("/api/monthly", params={"month": "2026-13"})

    assert response.status_code == 400
    assert response.json()["field"] == "month"
    assert response.json()["error"]


def test_malformed_month_answers_400(client):
    assert client.get("/api/monthly", params={"month": "august"}).status_code == 400


def test_bearer_token_opens_the_api_and_no_token_answers_401(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    auth = AuthSettings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_secret="session-secret",
        base_url="http://testserver",
        api_token="s3cret-token",
    )
    app = create_app(db_path, auth=auth, google=FakeGoogle())
    with TestClient(app, follow_redirects=False) as client:
        refused = client.get("/api/monthly")
        allowed = client.get("/api/monthly", headers={"Authorization": "Bearer s3cret-token"})
        listed = client.get("/api/transactions", headers={"Authorization": "Bearer s3cret-token"})

    assert refused.status_code == 401
    assert allowed.status_code == 200
    assert listed.status_code == 200
