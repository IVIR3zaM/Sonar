"""Error-path tests for the Settings page (SPEC §8, §12): one invalid field
per request must return 400, leave settings/balance unchanged, show an
inline #form-error alert, and keep the entered value.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.cashflow.store import current_balance, load_settings
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.web.app import create_app
from tests.html import soup, text
from tests.seed import seed

TODAY = date(2026, 9, 23)
TOMORROW = date(2026, 9, 24)


def _app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    return create_app(db_path, today=lambda: TODAY), db_path


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


def test_bad_overdraft_limit_shows_form_error_and_keeps_value(tmp_path):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/settings", data={"salary_day": "26", "overdraft_limit": "5"})

    assert response.status_code == 400
    page = soup(response)
    form = page.select_one("#settings-form")
    assert form.select_one("#form-error")["role"] == "alert"
    assert form.select_one('input[name="overdraft_limit"]')["value"] == "5"
    assert form.select_one('input[name="salary_day"]')["value"] == "26"
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


def test_bad_salary_day_shows_form_error_and_keeps_value(tmp_path):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/settings", data={"salary_day": "32", "overdraft_limit": "-500.00"})

    assert response.status_code == 400
    page = soup(response)
    form = page.select_one("#settings-form")
    assert form.select_one("#form-error")["role"] == "alert"
    assert form.select_one('input[name="salary_day"]')["value"] == "32"
    assert _settings(db_path).salary_day is None


@pytest.mark.parametrize("amount", INVALID_BALANCE_AMOUNT_VALUES)
def test_bad_balance_amount_returns_400_and_stores_nothing(tmp_path, amount):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/settings/balance", data={"amount": amount, "as_of": "2026-09-20"})
        assert response.status_code == 400

    assert _balance(db_path) is None


def test_bad_balance_amount_shows_form_error_and_keeps_value(tmp_path):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/settings/balance", data={"amount": "abc", "as_of": "2026-09-20"})

    assert response.status_code == 400
    page = soup(response)
    form = page.select_one("#balance-form")
    assert form.select_one("#form-error")["role"] == "alert"
    assert form.select_one('input[name="amount"]')["value"] == "abc"
    assert form.select_one('input[name="as_of"]')["value"] == "2026-09-20"
    assert _balance(db_path) is None


@pytest.mark.parametrize("as_of", INVALID_AS_OF_VALUES)
def test_bad_as_of_returns_400_and_stores_nothing(tmp_path, as_of):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/settings/balance", data={"amount": "-100.00", "as_of": as_of})
        assert response.status_code == 400

    assert _balance(db_path) is None


# (route, form data, the exact #form-error text). A malformed field gets
# "<Label>: <hint>"; a value that parses but fails the domain check (e.g. day
# 32, a positive overdraft limit, a future date) gets a full-sentence message.
FRIENDLY_CASES = [
    (
        "/settings",
        {"salary_day": "32", "overdraft_limit": "-500.00"},
        "Salary day must be between 1 and 31.",
    ),
    (
        "/settings",
        {"salary_day": "x", "overdraft_limit": "-500.00"},
        "Salary day: enter a whole number",
    ),
    (
        "/settings",
        {"salary_day": "26", "overdraft_limit": "5"},
        "Overdraft limit must be zero or negative.",
    ),
    (
        "/settings",
        {"salary_day": "26", "overdraft_limit": "abc"},
        "Overdraft limit: enter a number like 1234.56 or -250.50",
    ),
    (
        "/settings/balance",
        {"amount": "abc", "as_of": "2026-09-20"},
        "Amount: enter a number like 1234.56 or -250.50",
    ),
    (
        "/settings/balance",
        {"amount": "-100.00", "as_of": "2026-13-01"},
        "As of: pick a date",
    ),
    (
        "/settings/balance",
        {"amount": "-100.00", "as_of": TOMORROW.isoformat()},
        "That date cannot be in the future.",
    ),
]


@pytest.mark.parametrize("route,data,expected", FRIENDLY_CASES)
def test_settings_error_message_is_friendly(tmp_path, route, data, expected):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(route, data=data)

    assert response.status_code == 400
    alert = soup(response).select_one("#form-error")
    assert text(alert) == expected
    assert alert["tabindex"] == "-1"
    assert "got " not in text(alert)
    assert "_" not in text(alert)
