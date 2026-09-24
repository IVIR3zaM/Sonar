"""Settings page tests (SPEC §8): salary day, overdraft limit, manual balance."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations
from sonar.settings_store import load_settings

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 23)


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


def _app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)
    return create_app(db_path, categories_path=categories_path, today=lambda: TODAY), db_path


def _load_settings(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        return load_settings(conn)
    finally:
        conn.close()


def test_get_settings_shows_default_overdraft_limit(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/settings")

    assert response.status_code == 200
    assert "-500.00" in response.text
    assert "No balance yet" in response.text


def test_post_settings_saves_and_overwrites(tmp_path):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/settings",
            data={"salary_day": "26", "overdraft_limit": "-750,50"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/settings"

        settings = _load_settings(db_path)
        assert settings.salary_day == 26
        assert settings.overdraft_limit_cents == -75050

        response = client.post(
            "/settings",
            data={"salary_day": "26", "overdraft_limit": "0"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    settings = _load_settings(db_path)
    assert settings.overdraft_limit_cents == 0


def test_balance_display_manual_then_later_import_wins_and_survives_restart(tmp_path):
    app, db_path = _app(tmp_path)
    categories_path = _empty_categories(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/settings/balance",
            data={"amount": "-250.50", "as_of": "2026-09-20"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/settings"

        page = client.get("/settings")
        assert "Current balance: -250.50 as of 2026-09-20 (manual)" in page.text

    # An import row (as if from a CSV upload) dated after the manual entry wins.
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        conn.execute(
            "INSERT INTO balances (account, as_of, amount_cents, source) "
            "VALUES (?, ?, ?, 'import')",
            ("Girokonto", "2026-09-21", -30000),
        )
        conn.commit()
    finally:
        conn.close()

    # A fresh app/client on the same db is a restart; both rows must survive.
    app2 = create_app(db_path, categories_path=categories_path, today=lambda: TODAY)
    with TestClient(app2) as client:
        page = client.get("/settings")
        assert "Current balance: -300.00 as of 2026-09-21 (import)" in page.text


def test_settings_nav_link_present(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        page = client.get("/settings")

    assert 'href="/settings"' in page.text
    assert "Settings" in page.text


def test_post_settings_prefills_form_with_saved_values(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/settings",
            data={"salary_day": "26", "overdraft_limit": "-750,50"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get("/settings")
        assert 'name="salary_day" value="26"' in page.text
        assert 'name="overdraft_limit" value="-750.50"' in page.text


def test_balance_form_as_of_defaults_to_today(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        page = client.get("/settings")

    # _app pins today to TODAY (2026-09-23), so the date input must default to it.
    assert '<input name="as_of" type="date" value="2026-09-23" required>' in page.text
