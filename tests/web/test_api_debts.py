"""Tests for the JSON API's debt endpoints (SPEC §7, §13 Debts API): N02."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.auth.settings import AuthSettings
from sonar.categorization.service import add_rule
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.debts.store import debt_overview, list_debts, remaining_cents
from sonar.web.app import create_app

TODAY = date(2026, 9, 23)
LOANS = "Loans & Installments"
TOKEN = "s3cret-token"
AUTH = AuthSettings(
    google_client_id="client-id",
    google_client_secret="client-secret",
    session_secret="session-secret",
    base_url="http://testserver",
    api_token=TOKEN,
)

ITEM_KEYS = {
    "id",
    "kind",
    "name",
    "match_field",
    "match_value",
    "rate_cents",
    "total_cents",
    "interval_months",
    "first_payment_date",
    "payments_count",
    "balance_cents",
    "balance_as_of",
    "interest_bp",
    "paid_cents",
    "remaining_cents",
    "payments_remaining",
    "end_date",
    "paid_off",
    "linked_payment_ids",
}

INSTALLMENT = {
    "kind": "installment",
    "name": "Car Bank",
    "total_cents": 120_000,
    "rate_cents": 10_000,
    "interval_months": 1,
    "first_payment_date": "2026-07-05",
    "payments_count": 12,
    "match_field": "counterparty",
    "match_value": "Car Bank",
}
LOAN = {
    "kind": "loan",
    "name": "Home Bank",
    "balance_cents": 500_000,
    "balance_as_of": "2026-06-30",
    "rate_cents": 20_000,
    "match_field": "mandate",
    "match_value": "M-2",
}


def _today() -> date:
    return TODAY


def _insert_tx(conn: sqlite3.Connection, tag: str, booked: str, counterparty: str, mandate=None):
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES ('test', 'acc', ?, ?, -10000, 'EUR', ?, '', NULL, ?, NULL, 'raw', ?, 1, NULL)
        """,
        (booked, booked, counterparty, mandate, tag),
    )


@pytest.fixture
def db_path(tmp_path) -> Path:
    """Three monthly Car Bank debits filed under the debt category, so a draft exists."""
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        for month in (7, 8, 9):
            _insert_tx(conn, f"car{month}", f"2026-0{month}-05", "Car Bank")
        _insert_tx(conn, "home", "2026-08-10", "Home Bank", "M-2")
        add_rule(conn, TODAY, {"category": LOANS, "counterparty": "Car Bank"})
        conn.commit()
    finally:
        conn.close()
    return path


def _client(db_path: Path, auth: AuthSettings | None = None) -> TestClient:
    app = create_app(db_path, today=_today, auth=auth)
    return TestClient(app, follow_redirects=False)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _stored(db_path: Path):
    conn = connect(db_path)
    try:
        return list_debts(conn)
    finally:
        conn.close()


def _overview(db_path: Path):
    conn = connect(db_path)
    try:
        return debt_overview(conn, TODAY)
    finally:
        conn.close()


def _open_drafts(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM debt_drafts WHERE status = 'open'").fetchone()[0]
    finally:
        conn.close()


def test_post_installment_then_get_lists_it_with_every_key_and_status(db_path):
    with _client(db_path) as client:
        posted = client.post("/api/debts", json=INSTALLMENT)
        listed = client.get("/api/debts")

    assert posted.status_code == 201
    [item] = listed.json()
    assert set(item) == ITEM_KEYS
    assert posted.json() == item
    assert item["id"] == _stored(db_path)[0].id
    assert item["linked_payment_ids"] != []
    assert item == {
        "id": item["id"],
        "kind": "installment",
        "name": "Car Bank",
        "match_field": "counterparty",
        "match_value": "Car Bank",
        "rate_cents": 10_000,
        "total_cents": 120_000,
        "interval_months": 1,
        "first_payment_date": "2026-07-05",
        "payments_count": 12,
        "balance_cents": None,
        "balance_as_of": None,
        "interest_bp": None,
        "paid_cents": 30_000,
        "remaining_cents": 90_000,
        "payments_remaining": 9,
        "end_date": "2027-06-05",
        "paid_off": False,
        "linked_payment_ids": item["linked_payment_ids"],
    }


def test_get_lists_both_kinds_with_the_other_kinds_fields_null(db_path):
    with _client(db_path) as client:
        client.post("/api/debts", json={**LOAN, "interest_bp": 450})
        client.post("/api/debts", json=INSTALLMENT)
        items = client.get("/api/debts").json()

    assert [i["kind"] for i in items] == ["installment", "loan"]
    installment, loan = items
    assert set(installment) == set(loan) == ITEM_KEYS
    for key in ("balance_cents", "balance_as_of", "interest_bp"):
        assert installment[key] is None
    for key in ("total_cents", "interval_months", "first_payment_date", "payments_count"):
        assert loan[key] is None
    assert loan["payments_remaining"] is None
    assert loan["balance_cents"] == 500_000
    assert loan["balance_as_of"] == "2026-06-30"
    assert loan["interest_bp"] == 450


def test_status_figures_equal_the_debt_overview(db_path):
    with _client(db_path) as client:
        client.post("/api/debts", json={**LOAN, "interest_bp": 450})
        client.post("/api/debts", json=INSTALLMENT)
        items = client.get("/api/debts").json()

    views = _overview(db_path)
    assert [i["id"] for i in items] == [v.id for v in views]
    for item, view in zip(items, views, strict=True):
        assert item["paid_cents"] == (
            view.status.paid_cents
            if item["kind"] == "installment"
            else view.status.paid_since_statement_cents
        )
        assert item["remaining_cents"] == remaining_cents(view)
        assert item["paid_off"] == view.status.paid_off
    loan = items[1]
    assert loan["paid_cents"] == 10_000
    assert loan["end_date"] is not None


def test_linked_payment_ids_are_filled_and_ascending(db_path):
    conn = connect(db_path)
    try:
        for tag, name in (("a", "Alpha Shop"), ("b", "Beta Shop")):
            for month in (7, 8, 9):
                _insert_tx(conn, f"{tag}{month}", f"2026-0{month}-12", name)
        add_rule(conn, TODAY, {"category": LOANS, "counterparty": "Alpha Shop"})
        add_rule(conn, TODAY, {"category": LOANS, "counterparty": "Beta Shop"})
        conn.commit()
    finally:
        conn.close()
    body = {**LOAN, "name": "Shops", "match_field": "counterparty", "match_value": "Shop"}
    with _client(db_path) as client:
        client.post("/api/debts", json=body)
        [item] = client.get("/api/debts").json()

    [view] = _overview(db_path)
    assert item["linked_payment_ids"] == sorted(p.id for p in view.linked_payments)
    assert len(item["linked_payment_ids"]) == 2
    assert item["linked_payment_ids"] == sorted(item["linked_payment_ids"])


def test_post_loan_without_interest_is_linear(db_path):
    with _client(db_path) as client:
        response = client.post("/api/debts", json=LOAN)

    assert response.status_code == 201
    assert response.json()["interest_bp"] is None
    assert response.json()["kind"] == "loan"
    assert _stored(db_path)[0].debt.interest_bp is None


def test_post_loan_with_interest(db_path):
    with _client(db_path) as client:
        response = client.post("/api/debts", json={**LOAN, "interest_bp": 450})

    assert response.status_code == 201
    assert response.json()["interest_bp"] == 450
    assert _stored(db_path)[0].debt.interest_bp == 450


def test_post_linking_a_drafted_payment_leaves_no_open_draft(db_path):
    with _client(db_path) as client:
        page_before = client.get("/debts")
        response = client.post("/api/debts", json=INSTALLMENT)
        page_after = client.get("/debts")

    assert "data-draft-id" in page_before.text
    assert response.status_code == 201
    assert "data-draft-id" not in page_after.text
    assert _open_drafts(db_path) == 0


def _without(body: dict, key: str) -> dict:
    return {k: v for k, v in body.items() if k != key}


@pytest.mark.parametrize(
    "body,field",
    [
        ({**INSTALLMENT, "kind": "mortgage"}, "kind"),
        (_without(INSTALLMENT, "kind"), "kind"),
        ({**INSTALLMENT, "balance_cents": 5}, "balance_cents"),
        ({**LOAN, "total_cents": 5}, "total_cents"),
        ({**LOAN, "payments_count": 3}, "payments_count"),
        (_without(INSTALLMENT, "name"), "name"),
        (_without(INSTALLMENT, "payments_count"), "payments_count"),
        ({**INSTALLMENT, "match_value": None}, "match_value"),
        (_without(LOAN, "balance_as_of"), "balance_as_of"),
        ({**INSTALLMENT, "first_payment_date": "05/07/2026"}, "first_payment_date"),
        ({**LOAN, "balance_as_of": "yesterday"}, "balance_as_of"),
        ({**INSTALLMENT, "total_cents": 0}, "total_cents"),
        ({**INSTALLMENT, "total_cents": -5}, "total_cents"),
        ({**INSTALLMENT, "name": "  "}, "name"),
        ({**INSTALLMENT, "rate_cents": 0}, "rate_cents"),
        ({**INSTALLMENT, "interval_months": 0}, "interval_months"),
        ({**INSTALLMENT, "payments_count": 0}, "payments_count"),
        ({**LOAN, "balance_cents": 0}, "balance_cents"),
        ({**LOAN, "interest_bp": 0}, "interest_bp"),
        ({**INSTALLMENT, "match_field": "iban"}, "match_field"),
        ({**INSTALLMENT, "match_value": " "}, "match_value"),
    ],
)
def test_post_bad_body_answers_400_with_the_field_and_stores_nothing(db_path, body, field):
    with _client(db_path) as client:
        response = client.post("/api/debts", json=body)

    assert response.status_code == 400
    assert response.json()["field"] == field
    assert response.json()["error"]
    assert _stored(db_path) == []


def test_post_missing_fields_are_reported_in_the_documented_order(db_path):
    with _client(db_path) as client:
        response = client.post("/api/debts", json={"kind": "installment", "match_value": "x"})

    assert response.json()["field"] == "name"


@pytest.mark.parametrize(
    "body",
    [
        {**INSTALLMENT, "colour": "red"},
        {**INSTALLMENT, "total_cents": "1200"},
        {**LOAN, "balance_cents": "lots"},
        {**INSTALLMENT, "first_payment_date": 20260705},
        {**INSTALLMENT, "name": 5},
    ],
)
def test_post_unknown_key_or_wrong_json_type_answers_422(db_path, body):
    with _client(db_path) as client:
        response = client.post("/api/debts", json=body)

    assert response.status_code == 422
    assert _stored(db_path) == []


def test_delete_returns_the_item_and_a_second_delete_is_404(db_path):
    with _client(db_path) as client:
        created = client.post("/api/debts", json=INSTALLMENT).json()
        first = client.delete(f"/api/debts/{created['id']}")
        second = client.delete(f"/api/debts/{created['id']}")
        listed = client.get("/api/debts")

    assert first.status_code == 200
    assert first.json() == created
    assert second.status_code == 404
    assert second.json() == {"error": f"No such debt: {created['id']}"}
    assert listed.json() == []


def test_delete_leaves_drafts_as_they_are(db_path):
    with _client(db_path) as client:
        created = client.post("/api/debts", json=INSTALLMENT).json()
        client.delete(f"/api/debts/{created['id']}")

    assert _open_drafts(db_path) == 0


def test_with_sign_in_on_the_right_bearer_reaches_post_and_a_wrong_one_gets_401(db_path):
    with _client(db_path, auth=AUTH) as client:
        right = client.post("/api/debts", json=INSTALLMENT, headers=_bearer(TOKEN))
        wrong = client.post("/api/debts", json=LOAN, headers=_bearer("wrong"))

    assert right.status_code == 201
    assert wrong.status_code == 401
    assert len(_stored(db_path)) == 1
