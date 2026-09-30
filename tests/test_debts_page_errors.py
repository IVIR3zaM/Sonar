"""Error-path tests for the Installments and loans page (SPEC §7, §12): one
invalid field per request must return 400, leave the debts table unchanged,
show an inline #form-error alert in the failing form, and keep the submitted
values.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debt_store import list_debts
from tests.html import soup, text
from tests.seed import seed


def _assert_debts_table_empty(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        assert list_debts(conn) == []
    finally:
        conn.close()


VALID_INSTALLMENT = {
    "name": "Sofa",
    "total": "1200.00",
    "rate": "100.00",
    "interval_months": "1",
    "first_payment_date": "2026-01-05",
    "payments_count": "12",
    "match_field": "counterparty",
    "match_value": "Sofa Shop",
}

VALID_LOAN = {
    "name": "Car loan",
    "balance": "5000.00",
    "balance_as_of": "2026-06-30",
    "rate": "1000.00",
    "interest": "",
    "match_field": "mandate",
    "match_value": "CAR-1",
}

INSTALLMENT_CASES = [
    ("name", ""),
    ("total", "abc"),
    ("total", ""),
    ("rate", "0"),
    ("rate", ""),
    ("interval_months", "0"),
    ("interval_months", "x"),
    ("interval_months", ""),
    ("first_payment_date", "2026-13-01"),
    ("first_payment_date", ""),
    ("payments_count", "0"),
    ("payments_count", "x"),
    ("payments_count", ""),
    ("match_field", "iban"),
    ("match_field", ""),
    ("match_value", " "),
    ("match_value", ""),
]

LOAN_CASES = [
    ("name", ""),
    ("balance", "abc"),
    ("balance", ""),
    ("balance_as_of", "bad"),
    ("balance_as_of", ""),
    ("rate", "-5"),
    ("rate", ""),
    ("interest", "abc"),
    ("interest", "0"),
    ("match_field", "iban"),
    ("match_field", ""),
    ("match_value", ""),
]


@pytest.mark.parametrize("field,value", INSTALLMENT_CASES)
def test_bad_installment_field_returns_400(tmp_path, field, value):
    db_path = tmp_path / "t.db"
    seed(db_path)
    data = {**VALID_INSTALLMENT, field: value}

    with TestClient(create_app(db_path)) as client:
        response = client.post("/debts/installments", data=data)
        assert response.status_code == 400

    _assert_debts_table_empty(db_path)


def test_bad_installment_field_shows_form_error_and_keeps_values(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    data = {**VALID_INSTALLMENT, "interval_months": "0"}

    with TestClient(create_app(db_path)) as client:
        response = client.post("/debts/installments", data=data)

    assert response.status_code == 400
    page = soup(response)
    form = page.select_one("#add-installment")
    assert form.select_one("#form-error")["role"] == "alert"
    assert form.select_one('input[name="name"]')["value"] == "Sofa"
    assert form.select_one('input[name="interval_months"]')["value"] == "0"
    # The collapsible add-installment card opens on its own 400 re-render, so
    # the error and kept values are visible without an extra click.
    assert page.select_one("#add-installment-details").has_attr("open")
    _assert_debts_table_empty(db_path)


@pytest.mark.parametrize("field,value", LOAN_CASES)
def test_bad_loan_field_returns_400(tmp_path, field, value):
    db_path = tmp_path / "t.db"
    seed(db_path)
    data = {**VALID_LOAN, field: value}

    with TestClient(create_app(db_path)) as client:
        response = client.post("/debts/loans", data=data)
        assert response.status_code == 400

    _assert_debts_table_empty(db_path)


def test_bad_loan_field_shows_form_error_and_keeps_values(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)
    data = {**VALID_LOAN, "balance": "abc"}

    with TestClient(create_app(db_path)) as client:
        response = client.post("/debts/loans", data=data)

    assert response.status_code == 400
    page = soup(response)
    form = page.select_one("#add-loan")
    assert form.select_one("#form-error")["role"] == "alert"
    assert form.select_one('input[name="name"]')["value"] == "Car loan"
    assert form.select_one('input[name="balance"]')["value"] == "abc"
    assert page.select_one("#add-loan-details").has_attr("open")
    # The installment card's details stay closed: only the failing form opens.
    assert not page.select_one("#add-installment-details").has_attr("open")
    _assert_debts_table_empty(db_path)


# (route, form field overrides, the exact #form-error text). A blank field
# gets a full-sentence domain message; a malformed field gets "<Label>: <hint>".
FRIENDLY_CASES = [
    ("installments", {"name": ""}, "Name must not be blank."),
    ("installments", {"total": "abc"}, "Total: enter a number like 1234.56 or -250.50"),
    (
        "installments",
        {"first_payment_date": "2026-13-01"},
        "First payment: pick a date",
    ),
    ("installments", {"payments_count": "x"}, "Number of payments: enter a whole number"),
    ("loans", {"balance": "abc"}, "Balance: enter a number like 1234.56 or -250.50"),
    ("loans", {"interest": "abc"}, "Interest: enter a percent like 3.5"),
]


@pytest.mark.parametrize("kind,override,expected", FRIENDLY_CASES)
def test_add_debt_error_message_is_friendly(tmp_path, kind, override, expected):
    db_path = tmp_path / "t.db"
    seed(db_path)
    base = VALID_INSTALLMENT if kind == "installments" else VALID_LOAN
    data = {**base, **override}

    with TestClient(create_app(db_path)) as client:
        response = client.post(f"/debts/{kind}", data=data)

    assert response.status_code == 400
    alert = soup(response).select_one("#form-error")
    assert text(alert) == expected
    assert alert["tabindex"] == "-1"
    assert "got " not in text(alert)
    assert "_" not in text(alert)


def test_delete_unknown_debt_returns_404(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path)) as client:
        response = client.post("/debts/999/delete")
        assert response.status_code == 404
        assert soup(response).select_one("#error-page") is not None

    _assert_debts_table_empty(db_path)
