"""Settings page tests (SPEC §8): salary day, overdraft limit, manual balance."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations
from sonar.display import eur
from sonar.settings_store import load_settings
from tests.html import cents, fields, soup, text

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


def _input_value(page, form_id: str, name: str) -> str:
    return page.select_one(f'#{form_id} input[name="{name}"]')["value"]


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
    page = soup(response)
    assert _input_value(page, "settings-form", "overdraft_limit") == "-500.00"
    current = page.select_one("#current-balance")
    assert current.select("[data-cents]") == []
    assert text(current) == "No balance yet"


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

        current = soup(client.get("/settings")).select_one("#current-balance")
        assert fields(current) == {"amount": -25_050, "as_of": "2026-09-20", "source": "manual"}

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
        current = soup(client.get("/settings")).select_one("#current-balance")
        assert fields(current) == {"amount": -30_000, "as_of": "2026-09-21", "source": "import"}


def test_settings_nav_link_present(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        page = soup(client.get("/settings"))

    assert text(page.select_one('a[href="/settings"]')) == "Settings"


def test_post_settings_prefills_form_with_saved_values(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/settings",
            data={"salary_day": "26", "overdraft_limit": "-750,50"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = soup(client.get("/settings"))
        assert _input_value(page, "settings-form", "salary_day") == "26"
        assert _input_value(page, "settings-form", "overdraft_limit") == "-750.50"


def test_balance_form_as_of_defaults_to_today(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        page = soup(client.get("/settings"))

    # _app pins today to TODAY (2026-09-23), so the date input must default to it.
    as_of = page.select_one('#balance-form input[name="as_of"]')
    assert (as_of["type"], as_of["value"]) == ("date", "2026-09-23")
    assert as_of.has_attr("required")


def test_every_settings_input_has_a_label(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        page = soup(client.get("/settings"))

    for control in page.select(
        "#settings-form input, #settings-form select, #balance-form input, #balance-form select"
    ):
        field_id = control["id"]
        label = page.select_one(f'label[for="{field_id}"]')
        assert label is not None, f"no label for {field_id}"


def test_salary_day_and_overdraft_limit_have_help_text(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        page = soup(client.get("/settings"))

    salary_day = page.select_one('#settings-form input[name="salary_day"]')
    overdraft_limit = page.select_one('#settings-form input[name="overdraft_limit"]')
    for control in (salary_day, overdraft_limit):
        describedby = control["aria-describedby"].split()
        help_texts = [text(page.select_one(f"#{ref}")) for ref in describedby]
        assert any(help_texts), f"no help text for {control['name']}"


def test_current_balance_has_data_cents_and_eur_text(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        client.post("/settings/balance", data={"amount": "-250.50", "as_of": "2026-09-20"})
        current = soup(client.get("/settings")).select_one("#current-balance")

    assert cents(current) == -25_050
    # text() collapses all whitespace (including the eur filter's non-breaking
    # space) to plain spaces, so normalize the same way before comparing.
    assert " ".join(eur(-25_050).split()) in text(current)
