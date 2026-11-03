"""Category controls for manual fixed payments."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sonar.categorization.store import add_category
from sonar.db import connect
from sonar.web.app import create_app
from tests.html import fields, soup, text
from tests.seed import seed

ADD = {
    "name": "Music",
    "amount": "12.99",
    "interval_months": "1",
    "day": "15",
    "starts_on": "2026-01-15",
}


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "categories.db"
    seed(path)
    with connect(path) as conn:
        add_category(conn, "Housing", "fixed")
        add_category(conn, "Subscriptions", "fixed")
        add_category(conn, "Snacks", "occasional")
    with TestClient(create_app(path, today=lambda: date(2026, 9, 23))) as client:
        client.db_path = path
        yield client


def payment(client):
    [payment] = client.get("/api/recurring").json()
    return payment


def selected(control):
    return control.select_one("option[selected]")["value"]


@pytest.mark.parametrize("category", ["Subscriptions", ""])
def test_add_category_is_shown_and_listed(client, category):
    response = client.post("/recurring", data={**ADD, "category": category})
    assert response.status_code == 200
    [row] = soup(response).select("#payments [data-payment-id]")
    assert fields(row)["category"] == category
    assert payment(client)["category"] == (category or None)


def test_edit_sets_and_clears_category(client):
    client.post("/recurring", data=ADD)
    uid = payment(client)["id"]
    for category in ("Subscriptions", ""):
        response = client.post(f"/recurring/{uid}/edit", data={**ADD, "category": category})
        assert response.status_code == 200
        page = soup(response)
        assert selected(page.select_one(f"#edit-category-payment-{uid}")) == category
        assert payment(client)["category"] == (category or None)


def test_options_are_none_and_only_fixed_categories(client):
    client.post("/recurring", data=ADD)
    page = soup(client.get("/recurring"))
    uid = payment(client)["id"]
    for selector in ("#field-category", f"#edit-category-payment-{uid}"):
        control = page.select_one(selector)
        assert control is not None
        options = [(option["value"], text(option)) for option in control.select("option")]
        assert options == [("", "None"), ("Housing", "Housing"), ("Subscriptions", "Subscriptions")]
        assert selected(control) == ""


@pytest.mark.parametrize("category", ["Unknown", "Snacks"])
@pytest.mark.parametrize("edit", [False, True])
def test_bad_category_keeps_submission_and_stores_nothing(client, category, edit):
    route = "/recurring"
    selector = "#field-category"
    if edit:
        client.post(route, data={**ADD, "category": "Subscriptions"})
        uid = payment(client)["id"]
        route = f"/recurring/{uid}/edit"
        selector = f"#edit-category-payment-{uid}"
    before = client.get("/api/recurring").json()
    response = client.post(route, data={**ADD, "name": "Changed", "category": category})
    assert response.status_code == 400
    page = soup(response)
    assert page.select_one("#form-error") is not None
    assert selected(page.select_one(selector)) == category
    assert client.get("/api/recurring").json() == before


@pytest.mark.parametrize("edit", [False, True])
def test_other_error_keeps_valid_category(client, edit):
    route = "/recurring"
    selector = "#field-category"
    if edit:
        client.post(route, data=ADD)
        uid = payment(client)["id"]
        route = f"/recurring/{uid}/edit"
        selector = f"#edit-category-payment-{uid}"
    response = client.post(route, data={**ADD, "amount": "bad", "category": "Subscriptions"})
    assert response.status_code == 400
    assert selected(soup(response).select_one(selector)) == "Subscriptions"


def test_detected_payment_has_no_select_and_ignores_category(client):
    client.post("/recurring", data=ADD)
    uid = payment(client)["id"]
    with connect(client.db_path) as conn:
        conn.execute(
            "UPDATE recurring_payments SET source = 'detected', category = 'Housing' WHERE id = ?",
            (uid,),
        )
    response = client.post(f"/recurring/{uid}/edit", data={**ADD, "category": "Unknown"})
    assert response.status_code == 200
    row = soup(response).select_one(f"#payment-{uid}")
    assert row.select_one(f"#edit-category-payment-{uid}") is None
    assert fields(row)["category"] == "Housing"
    assert payment(client)["category"] == "Housing"


def test_stale_non_fixed_category_preselects_none(client):
    client.post("/recurring", data=ADD)
    uid = payment(client)["id"]
    with connect(client.db_path) as conn:
        conn.execute("UPDATE recurring_payments SET category = 'Snacks' WHERE id = ?", (uid,))
    page = soup(client.get("/recurring"))
    assert selected(page.select_one(f"#edit-category-payment-{uid}")) == ""
