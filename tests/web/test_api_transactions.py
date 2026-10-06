"""Tests for GET /api/transactions (SPEC §13 Pages): the stored transactions as JSON, filtered."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
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

# (counterparty, purpose, booking date, cents, category)
ROWS = [
    ("Fake Market", "weekly shop", "2026-01-05", -3100, "Groceries"),
    ("Fake Bistro", "dinner", "2026-01-12", -620, "Dining"),
    ("Unknown Ltd", "Invoice 7", "2026-01-20", -900, None),
    ("Mystery Co", "refund", "2026-01-28", 500, None),
    ("Fake Market", "weekly shop", "2026-02-02", -2500, "Groceries"),
    ("Unknown Ltd", "Invoice 8", "2026-02-09", -700, None),
]


def _insert_all(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        for index, (counterparty, purpose, booking, cents, category) in enumerate(ROWS):
            conn.execute(
                """
                INSERT INTO transactions (
                    source, account, booking_date, value_date, amount_cents, currency,
                    counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                    fingerprint, occurrence, category
                ) VALUES (
                    'test', 'acc', ?, ?, ?, 'EUR', ?, ?, 'DE00FAKE', 'M1', 'C1', 'raw', ?, 1, ?
                )
                """,
                (booking, booking, cents, counterparty, purpose, f"fp{index}", category),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, TOML)
    _insert_all(db_path)
    with TestClient(create_app(db_path, today=lambda: date(2026, 9, 10))) as client:
        # The rules categorize the seeded rows.
        client.post("/api/reapply")
        yield client


def _purposes(response) -> list[str]:
    return [item["purpose"] for item in response.json()["transactions"]]


def test_january_uncategorized_is_newest_first_without_raw_row(client):
    response = client.get(
        "/api/transactions",
        params={"from": "2026-01-01", "to": "2026-01-31", "uncategorized": "true"},
    )

    assert response.status_code == 200
    assert _purposes(response) == ["refund", "Invoice 7"]
    assert response.json()["transactions"][1] == {
        "booking_date": "2026-01-20",
        "value_date": "2026-01-20",
        "amount_cents": -900,
        "currency": "EUR",
        "counterparty": "Unknown Ltd",
        "purpose": "Invoice 7",
        "account": "acc",
        "iban": "DE00FAKE",
        "mandate_ref": "M1",
        "creditor_id": "C1",
        "category": None,
    }


def test_without_filters_every_transaction_comes_newest_first(client):
    response = client.get("/api/transactions")

    assert _purposes(response) == [
        "Invoice 8",
        "weekly shop",
        "refund",
        "Invoice 7",
        "dinner",
        "weekly shop",
    ]


def test_range_bounds_are_inclusive(client):
    response = client.get("/api/transactions", params={"from": "2026-01-12", "to": "2026-01-20"})

    assert _purposes(response) == ["Invoice 7", "dinner"]


def test_a_single_bound_is_enough(client):
    assert _purposes(client.get("/api/transactions", params={"from": "2026-02-01"})) == [
        "Invoice 8",
        "weekly shop",
    ]
    assert _purposes(client.get("/api/transactions", params={"to": "2026-01-05"})) == [
        "weekly shop"
    ]


def test_category_is_an_exact_match(client):
    response = client.get("/api/transactions", params={"category": "Groceries"})

    assert [item["category"] for item in response.json()["transactions"]] == ["Groceries"] * 2
    assert _purposes(client.get("/api/transactions", params={"category": "Grocer"})) == []


def test_uncategorized_false_keeps_every_row(client):
    response = client.get("/api/transactions", params={"uncategorized": "false"})

    assert len(response.json()["transactions"]) == len(ROWS)


def test_q_matches_counterparty_case_insensitively(client):
    response = client.get("/api/transactions", params={"q": "FAKE bistro"})

    assert _purposes(response) == ["dinner"]


def test_q_matches_purpose_only(client):
    response = client.get("/api/transactions", params={"q": "INVOICE"})

    assert _purposes(response) == ["Invoice 8", "Invoice 7"]


def test_q_matches_counterparty_only(client):
    response = client.get("/api/transactions", params={"q": "mystery"})

    assert _purposes(response) == ["refund"]


def test_q_combines_with_a_range_and_uncategorized(client):
    january = {"from": "2026-01-01", "to": "2026-01-31", "q": "Unknown"}

    assert _purposes(client.get("/api/transactions", params=january)) == ["Invoice 7"]
    both = {**january, "uncategorized": "true", "q": "o"}
    assert _purposes(client.get("/api/transactions", params=both)) == ["refund", "Invoice 7"]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": "2026-13-01"}, "from"),
        ({"to": "yesterday"}, "to"),
        ({"uncategorized": "maybe"}, "uncategorized"),
        ({"category": "Groceries", "uncategorized": "true"}, "uncategorized"),
    ],
)
def test_bad_input_answers_400_naming_the_field(client, params, field):
    response = client.get("/api/transactions", params=params)

    assert response.status_code == 400
    assert response.json()["field"] == field
    assert response.json()["error"]
