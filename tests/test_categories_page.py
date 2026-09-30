"""Tests for the Categories page (SPEC §5, §12): the Categories card (N08).

The Rules card is added by N09; this file only covers category CRUD, group
sections, friendly errors and the links from Settings and Uncategorized.
"""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from tests.html import cents, soup, text
from tests.seed import seed

TODAY = date(2026, 9, 23)

DINING_RULE_TOML = """
[[category]]
name = "Dining"
type = "occasional"

[[rule]]
category = "Dining"
counterparty = "Fake Diner"
"""

FITNESS_RULE_TOML = """
[[category]]
name = "Fitness"
type = "fixed"

[[rule]]
category = "Fitness"
counterparty = "Fake Gym"
"""


def _fresh_app(tmp_path: Path):
    # A truly fresh DB (only the 0006 migration's 17-category generic seed),
    # unlike tests.seed.seed which replaces the taxonomy with the given TOML.
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()
    return create_app(db_path, today=lambda: TODAY), db_path


def _seeded_app(tmp_path: Path, toml_text: str):
    db_path = tmp_path / "t.db"
    seed(db_path, toml_text)
    return create_app(db_path, today=lambda: TODAY), db_path


def _insert(
    conn: sqlite3.Connection, *, fingerprint: str, booking_date: str, counterparty: str
) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', ?, ?, -5000, 'EUR', ?, '', NULL, NULL, NULL, 'raw', ?, 1, NULL
        )
        """,
        (booking_date, booking_date, counterparty, fingerprint),
    )
    conn.commit()


def _category_id(db_path: Path, name: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]
    finally:
        conn.close()


def _category_names(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM categories").fetchall()}
    finally:
        conn.close()


def test_fresh_db_lists_17_seed_categories_under_their_groups(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        page = soup(client.get("/categories"))

    assert len(page.select("[data-category-id]")) == 17
    income = page.select_one("#group-income")
    assert "Salary" in text(income)
    fixed = page.select_one("#group-fixed")
    assert "Housing" in text(fixed)
    lights_on = page.select_one("#group-lights_on")
    assert "Groceries" in text(lights_on)
    occasional = page.select_one("#group-occasional")
    assert "Donations" in text(occasional)


def test_add_category_then_shows_under_its_group(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/categories", data={"name": "Pets", "group": "occasional"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/categories"

        page = soup(client.get("/categories"))
        occasional = page.select_one("#group-occasional")
        assert "Pets" in text(occasional)


def test_editing_dining_to_lights_on_moves_it_and_updates_monthly(tmp_path):
    app, db_path = _seeded_app(tmp_path, DINING_RULE_TOML)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="d1", booking_date="2026-09-05", counterparty="Fake Diner")
    finally:
        conn.close()
    dining_id = _category_id(db_path, "Dining")

    with TestClient(app) as client:
        response = client.post(
            f"/categories/{dining_id}/edit",
            data={"name": "Dining", "group": "lights_on"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = soup(client.get("/categories"))
        assert "Dining" in text(page.select_one("#group-lights_on"))
        assert page.select_one("#group-occasional") is not None
        assert "Dining" not in text(page.select_one("#group-occasional"))

        # The re-apply during the edit kept "Fake Diner" matched to Dining
        # (now lights_on), so its amount now counts in the lights-on total.
        monthly = soup(client.get("/monthly?month=2026-09"))
        assert cents(monthly.select_one("#group-lights-on")) == -5000

    conn = sqlite3.connect(db_path)
    try:
        category = conn.execute(
            "SELECT category FROM transactions WHERE fingerprint = 'd1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert category == "Dining"


def test_renaming_a_category_with_a_rule_keeps_transactions_categorized(tmp_path):
    app, db_path = _seeded_app(tmp_path, DINING_RULE_TOML)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="d1", booking_date="2026-09-05", counterparty="Fake Diner")
    finally:
        conn.close()
    dining_id = _category_id(db_path, "Dining")

    with TestClient(app) as client:
        response = client.post(
            f"/categories/{dining_id}/edit",
            data={"name": "Dinners", "group": "occasional"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    conn = sqlite3.connect(db_path)
    try:
        category = conn.execute(
            "SELECT category FROM transactions WHERE fingerprint = 'd1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert category == "Dinners"


def test_add_category_blank_or_duplicate_name_returns_400_and_keeps_values(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/categories", data={"name": "   ", "group": "occasional"})
        assert response.status_code == 400
        page = soup(response)
        error = page.select_one("#form-error")
        assert error is not None
        assert text(error) == "Name must not be blank."

        response = client.post("/categories", data={"name": "Housing", "group": "occasional"})
        assert response.status_code == 400
        page = soup(response)
        error = page.select_one("#form-error")
        assert error is not None
        assert "already exists" in text(error)
        assert page.select_one('#add-category-form input[name="name"]')["value"] == "Housing"


def test_delete_category_with_a_rule_returns_400_and_keeps_it(tmp_path):
    app, db_path = _seeded_app(tmp_path, DINING_RULE_TOML)
    dining_id = _category_id(db_path, "Dining")

    with TestClient(app) as client:
        response = client.post(f"/categories/{dining_id}/delete")
        assert response.status_code == 400
        page = soup(response)
        row = page.select_one(f'[data-category-id="{dining_id}"]')
        assert row is not None
        error = row.select_one("#form-error")
        assert error is not None
        assert "used by" in text(error)

    assert "Dining" in _category_names(db_path)


def test_deleting_an_unused_category_removes_it(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    donations_id = _category_id(db_path, "Donations")

    with TestClient(app) as client:
        response = client.post(f"/categories/{donations_id}/delete", follow_redirects=False)
        assert response.status_code == 303

    assert "Donations" not in _category_names(db_path)


def test_unknown_category_id_returns_404(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        edit = client.post("/categories/999999/edit", data={"name": "X", "group": "occasional"})
        delete = client.post("/categories/999999/delete")

    assert edit.status_code == 404
    assert delete.status_code == 404


def test_changing_fixed_category_to_occasional_drops_its_detected_payment(tmp_path):
    app, db_path = _seeded_app(tmp_path, FITNESS_RULE_TOML)
    conn = sqlite3.connect(db_path)
    try:
        for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
            _insert(conn, fingerprint=f"gym{i}", booking_date=booking_date, counterparty="Fake Gym")
    finally:
        conn.close()
    fitness_id = _category_id(db_path, "Fitness")

    # The app's startup lifespan re-applies the taxonomy, detecting the three
    # matching rows just inserted as one recurring payment (SPEC §6).
    with TestClient(app) as client:
        page = soup(client.get("/recurring"))
        assert page.select_one("#payments-card") is not None
        assert "Fitness" in text(page.select_one("#payments-card"))

        response = client.post(
            f"/categories/{fitness_id}/edit",
            data={"name": "Fitness", "group": "occasional"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = soup(client.get("/recurring"))
        payments_card = page.select_one("#payments-card")
        assert payments_card is None or "Fitness" not in text(payments_card)


def test_settings_and_uncategorized_link_to_categories(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        settings = soup(client.get("/settings"))
        uncategorized = soup(client.get("/uncategorized"))

    assert settings.select_one('a[href="/categories"]') is not None
    assert uncategorized.select_one('a[href="/categories"]') is not None
