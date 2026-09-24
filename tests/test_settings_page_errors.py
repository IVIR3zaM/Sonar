"""Error-path tests for the Settings page (SPEC §8): one invalid field per
request must return 400 and leave settings/balance unchanged.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations
from sonar.settings_store import current_balance, load_settings

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 23)
TOMORROW = date(2026, 9, 24)


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


def _app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)
    return create_app(db_path, categories_path=categories_path, today=lambda: TODAY), db_path


def _settings(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        return load_settings(conn)
    finally:
        conn.close()


def _balance(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        return current_balance(conn)
    finally:
        conn.close()


# A positive overdraft_limit_cents is rejected by save_settings, so "5" and
# "0.01" (parsed to positive cents) are invalid here even though they are
# well-formed amounts.
INVALID_OVERDRAFT_VALUES = ["", "abc", "1.234", "5", "0.01", "--5"]
INVALID_SALARY_DAY_VALUES = ["", "x", "0", "32"]
INVALID_BALANCE_AMOUNT_VALUES = ["", "abc"]
INVALID_AS_OF_VALUES = ["", "2026-13-01", TOMORROW.isoformat()]


@pytest.mark.parametrize("overdraft_limit", INVALID_OVERDRAFT_VALUES)
def test_bad_overdraft_limit_returns_400_and_leaves_settings_unsaved(tmp_path, overdraft_limit):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/settings", data={"salary_day": "26", "overdraft_limit": overdraft_limit}
        )
        assert response.status_code == 400

    assert _settings(db_path).salary_day is None


@pytest.mark.parametrize("salary_day", INVALID_SALARY_DAY_VALUES)
def test_bad_salary_day_returns_400_and_leaves_settings_unsaved(tmp_path, salary_day):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/settings", data={"salary_day": salary_day, "overdraft_limit": "-500.00"}
        )
        assert response.status_code == 400

    assert _settings(db_path).salary_day is None


@pytest.mark.parametrize("amount", INVALID_BALANCE_AMOUNT_VALUES)
def test_bad_balance_amount_returns_400_and_stores_nothing(tmp_path, amount):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/settings/balance", data={"amount": amount, "as_of": "2026-09-20"})
        assert response.status_code == 400

    assert _balance(db_path) is None


@pytest.mark.parametrize("as_of", INVALID_AS_OF_VALUES)
def test_bad_as_of_returns_400_and_stores_nothing(tmp_path, as_of):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/settings/balance", data={"amount": "-100.00", "as_of": as_of})
        assert response.status_code == 400

    assert _balance(db_path) is None
