"""Tests for GET /api/lights-on (SPEC §13 Pages): the Keep-the-lights-on page as JSON."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.web.app import create_app
from tests.seed import seed

TOML = """
[[category]]
name = "Groceries"
type = "lights_on"

[[category]]
name = "Dining"
type = "occasional"

[[rule]]
category = "Groceries"
counterparty = "Fake Market"

[[rule]]
category = "Dining"
counterparty = "Fake Bistro"
"""


def _insert(db_path: Path, fingerprint: str, counterparty: str, booking: str, cents: int) -> None:
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
            (booking, booking, cents, counterparty, fingerprint),
        )
        conn.commit()
    finally:
        conn.close()


def _client(tmp_path: Path, with_data: bool) -> TestClient:
    db_path = tmp_path / "t.db"
    seed(db_path, TOML)
    if with_data:
        # January: 31 days, so 3100 / 31 = 100 and 620 / 31 = 20 cents a day.
        _insert(db_path, "g", "Fake Market", "2026-01-01", -3100)
        _insert(db_path, "d", "Fake Bistro", "2026-01-01", -620)
        # A credit on February 1 makes January a complete month.
        _insert(db_path, "m", "Unrelated", "2026-02-01", 100)
    return TestClient(create_app(db_path, today=lambda: date(2026, 9, 10)))


def test_with_data_returns_months_daily_and_categories(tmp_path):
    with _client(tmp_path, with_data=True) as client:
        response = client.get("/api/lights-on")

    body = response.json()
    assert response.status_code == 200
    assert body["categories"] == ["Groceries"]
    assert body["salary_months"] is False
    assert len(body["months"]) == 1
    january = body["months"][0]
    assert january["period"] == {"month": "2026-01-01", "start": "2026-01-01", "end": "2026-01-31"}
    assert january["used"] is True
    assert january["total_cents"] == 100
    assert january["by_category"] == {"Groceries": 100}
    assert january["occasional_cents"] == 20
    assert body["daily"]["expected_cents"] == 100
    assert body["daily"]["months_used"] == [january["period"]]


def test_without_transactions_months_are_empty_and_daily_is_null(tmp_path):
    with _client(tmp_path, with_data=False) as client:
        body = client.get("/api/lights-on").json()

    assert body == {
        "categories": ["Groceries"],
        "salary_months": False,
        "daily": None,
        "months": [],
    }
