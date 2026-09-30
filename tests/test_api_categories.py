"""Tests for the JSON API's category endpoints (SPEC §5, §13): N17."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from tests.html import soup, text

TODAY = date(2026, 9, 23)

GROUP_ORDER = ["income", "transfer", "fixed", "lights_on", "occasional"]


def _fresh_app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()
    return create_app(db_path, today=lambda: TODAY), db_path


def _category_id(db_path: Path, name: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]
    finally:
        conn.close()


def test_get_categories_lists_seed_categories_in_group_order(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/categories")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 17
    for item in items:
        assert {"id", "name", "group", "group_label", "rule_count"} == item.keys()
    groups = [item["group"] for item in items]
    assert groups == sorted(groups, key=GROUP_ORDER.index)


def test_add_category_then_lists_under_its_group(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/categories", json={"name": "Pets", "group": "occasional"})

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Pets"
        assert body["group"] == "occasional"
        assert body["rule_count"] == 0
        assert "uncategorized" in body

        listed = client.get("/api/categories").json()
        assert any(c["name"] == "Pets" for c in listed)


def test_put_category_renames_it(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/categories", json={"name": "Pets", "group": "occasional"})
        pets_id = _category_id(db_path, "Pets")

        response = client.put(
            f"/api/categories/{pets_id}", json={"name": "Cats", "group": "occasional"}
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Cats"


def test_delete_category_removes_it(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/categories", json={"name": "Pets", "group": "occasional"})
        pets_id = _category_id(db_path, "Pets")

        response = client.delete(f"/api/categories/{pets_id}")

        assert response.status_code == 200
        assert response.json()["name"] == "Pets"
        listed = client.get("/api/categories").json()
        assert all(c["name"] != "Pets" for c in listed)


def test_blank_duplicate_and_bogus_group_return_400_with_field(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/categories", json={"name": "   ", "group": "occasional"})
        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "Name must not be blank."
        assert body["field"] == "name"

        response = client.post("/api/categories", json={"name": "Housing", "group": "occasional"})
        assert response.status_code == 400
        assert "already exists" in response.json()["error"]
        assert response.json()["field"] == "name"

        response = client.post("/api/categories", json={"name": "Pets", "group": "bogus"})
        assert response.status_code == 400
        assert response.json()["field"] == "group"


def test_delete_category_with_a_rule_returns_400(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/rules", json={"category": "Groceries", "counterparty": "testmarkt"})
        groceries_id = _category_id(db_path, "Groceries")

        response = client.delete(f"/api/categories/{groceries_id}")

        assert response.status_code == 400
        assert "used by" in response.json()["error"]


def test_unknown_category_id_returns_404_json(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        put = client.put("/api/categories/999999", json={"name": "X", "group": "occasional"})
        delete = client.delete("/api/categories/999999")

    assert put.status_code == 404
    assert put.json()["error"] == "No such category: 999999"
    assert delete.status_code == 404
    assert delete.json()["error"] == "No such category: 999999"


def test_unknown_json_field_returns_422(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/categories", json={"name": "Pets", "group": "occasional", "typo": "x"}
        )

    assert response.status_code == 422


def test_non_json_content_type_returns_415_and_changes_nothing(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        before = client.get("/api/categories").json()

        response = client.post(
            "/api/categories",
            content=b'{"name": "Pets", "group": "occasional"}',
            headers={"Content-Type": "text/plain"},
        )

        assert response.status_code == 415
        assert client.get("/api/categories").json() == before


def test_get_to_unknown_api_path_is_404_json_but_html_elsewhere(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        api_404 = client.get("/api/nope")
        page_404 = client.get("/nope")

    assert api_404.status_code == 404
    assert api_404.headers["content-type"].startswith("application/json")
    assert "error" in api_404.json()
    assert page_404.status_code == 404
    assert page_404.headers["content-type"].startswith("text/html")


def test_bad_regex_error_matches_the_page_error(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        page_response = client.post(
            "/categories/rules", data={"category": "Groceries", "purpose_regex": "("}
        )
        api_response = client.post(
            "/api/rules", json={"category": "Groceries", "purpose_regex": "("}
        )

    page = soup(page_response)
    assert page_response.status_code == 400
    assert api_response.status_code == 400
    assert text(page.select_one("#form-error")) == api_response.json()["error"]


def test_category_group_change_drops_its_detected_recurring_payment(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
            conn.execute(
                """
                INSERT INTO transactions (
                    source, account, booking_date, value_date, amount_cents, currency,
                    counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                    fingerprint, occurrence, category
                ) VALUES (
                    'test', 'acc', ?, ?, -5000, 'EUR', 'Fake Gym', '', NULL, NULL, NULL,
                    'raw', ?, 1, NULL
                )
                """,
                (booking_date, booking_date, f"gym{i}"),
            )
        conn.commit()
    finally:
        conn.close()

    with TestClient(app) as client:
        client.post("/api/rules", json={"category": "Insurance", "counterparty": "Fake Gym"})
        insurance_id = _category_id(db_path, "Insurance")

        page = soup(client.get("/recurring"))
        assert "Insurance" in text(page.select_one("#payments-card"))

        response = client.put(
            f"/api/categories/{insurance_id}", json={"name": "Insurance", "group": "occasional"}
        )
        assert response.status_code == 200

        page = soup(client.get("/recurring"))
        payments_card = page.select_one("#payments-card")
        assert payments_card is None or "Insurance" not in text(payments_card)
