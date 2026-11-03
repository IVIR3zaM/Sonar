"""Manual fixed categories through the recurring API (SPEC §13)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.categorization.store import add_category
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual, get_payment
from sonar.web.app import create_app


@pytest.fixture
def api(tmp_path):
    db_path = tmp_path / "categories.db"
    app = create_app(db_path, today=lambda: date(2026, 11, 3))
    conn = connect(db_path)
    apply_migrations(conn, MIGRATIONS_DIR)
    with conn:
        conn.execute("DELETE FROM category_rules")
        conn.execute("DELETE FROM categories")
    add_category(conn, "Subscriptions", "fixed")
    add_category(conn, "Groceries", "lights_on")
    with TestClient(app) as client:
        yield client, conn
    conn.close()


NEW = {
    "name": "Magazine",
    "amount_cents": 1000,
    "interval_months": 1,
    "day": 5,
    "starts_on": "2026-11-01",
}


def test_post_fixed_category_is_listed(api):
    client, _ = api
    response = client.post("/api/recurring", json={**NEW, "category": "Subscriptions"})
    assert response.status_code == 201
    assert response.json()["category"] == "Subscriptions"
    assert client.get("/api/recurring").json() == [response.json()]


@pytest.mark.parametrize("category", ["omitted", None, "", "   "])
def test_post_without_category(api, category):
    client, _ = api
    body = NEW if category == "omitted" else {**NEW, "category": category}
    response = client.post("/api/recurring", json=body)
    assert response.status_code == 201
    assert response.json()["category"] is None


@pytest.mark.parametrize("category", ["Unknown", "Groceries", " Subscriptions "])
def test_post_invalid_category_stores_nothing(api, category):
    client, _ = api
    response = client.post("/api/recurring", json={**NEW, "category": category})
    assert response.status_code == 400
    assert response.json()["field"] == "category"
    assert client.get("/api/recurring").json() == []


def test_put_set_and_omit_category(api):
    client, _ = api
    payment_id = client.post("/api/recurring", json=NEW).json()["id"]
    response = client.put(f"/api/recurring/{payment_id}", json={"category": "Subscriptions"})
    assert response.status_code == 200
    assert response.json()["category"] == "Subscriptions"
    kept = client.put(f"/api/recurring/{payment_id}", json={"description": "Reading"})
    assert kept.json()["category"] == "Subscriptions"


@pytest.mark.parametrize("category", [None, "", "   "])
def test_put_clear_category(api, category):
    client, _ = api
    payment_id = client.post("/api/recurring", json={**NEW, "category": "Subscriptions"}).json()[
        "id"
    ]
    response = client.put(f"/api/recurring/{payment_id}", json={"category": category})
    assert response.status_code == 200
    assert response.json()["category"] is None


@pytest.mark.parametrize("category", ["Unknown", "Groceries", " Subscriptions "])
def test_put_invalid_category_changes_nothing(api, category):
    client, conn = api
    payment_id = client.post("/api/recurring", json=NEW).json()["id"]
    before = get_payment(conn, payment_id)
    response = client.put(
        f"/api/recurring/{payment_id}",
        json={"category": category, "name": "Changed", "amount_cents": 2000},
    )
    assert response.status_code == 400
    assert response.json()["field"] == "category"
    assert get_payment(conn, payment_id) == before


@pytest.mark.parametrize("category", ["Subscriptions", None, ""])
def test_put_detected_category_is_rejected_before_any_write(api, category):
    client, conn = api
    period = SchedulePeriod(date(2026, 11, 1), None, 1000, 1, 5)
    payment_id = add_manual(conn, "Detected", "Subscriptions", period)
    with conn:
        conn.execute(
            "UPDATE recurring_payments SET source = 'detected', detection_key = 'test' "
            "WHERE id = ?",
            (payment_id,),
        )
    before = get_payment(conn, payment_id)
    response = client.put(
        f"/api/recurring/{payment_id}",
        json={"category": category, "name": "Changed", "amount_cents": 2000},
    )
    assert response.status_code == 400
    assert response.json()["field"] == "category"
    assert get_payment(conn, payment_id) == before


def test_put_unknown_payment_is_404(api):
    client, _ = api
    response = client.put("/api/recurring/999", json={"category": "Subscriptions"})
    assert response.status_code == 404
