"""Error-path tests for the Installments and loans page (SPEC §7): one invalid
field per request must return 400 and leave the debts table unchanged.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations
from sonar.debt_store import list_debts

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


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
    categories_path = _empty_categories(tmp_path)
    data = {**VALID_INSTALLMENT, field: value}

    with TestClient(create_app(db_path, categories_path=categories_path)) as client:
        response = client.post("/debts/installments", data=data)
        assert response.status_code == 400

    _assert_debts_table_empty(db_path)


@pytest.mark.parametrize("field,value", LOAN_CASES)
def test_bad_loan_field_returns_400(tmp_path, field, value):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)
    data = {**VALID_LOAN, field: value}

    with TestClient(create_app(db_path, categories_path=categories_path)) as client:
        response = client.post("/debts/loans", data=data)
        assert response.status_code == 400

    _assert_debts_table_empty(db_path)


def test_delete_unknown_debt_returns_404(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path)) as client:
        response = client.post("/debts/999/delete")
        assert response.status_code == 404

    _assert_debts_table_empty(db_path)
