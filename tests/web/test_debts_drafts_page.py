"""Needs-details debts on the Debts page (SPEC §13 Draft debts): cards, the two
completion forms and their routes. Fixtures are anonymized."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.categorization.service import add_rule
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts.store import list_debts
from sonar.web.app import create_app
from tests.html import fields, soup, text

LOANS = "Loans & Installments"
TODAY = date(2026, 9, 23)

VALID_INSTALLMENT = {
    "name": "Car Bank",
    "total": "1200.00",
    "rate": "100.00",
    "interval_months": "1",
    "first_payment_date": "2026-01-05",
    "payments_count": "12",
    "match_field": "mandate",
    "match_value": "M-1",
}
VALID_LOAN = {
    "name": "Car Bank",
    "balance": "5000.00",
    "balance_as_of": "2026-06-30",
    "rate": "100.00",
    "interest": "",
    "match_field": "mandate",
    "match_value": "M-1",
}


def _today() -> date:
    return TODAY


def _seed_car(db_path: Path, category: str | None = LOANS) -> None:
    """Three monthly mandate debits; a rule files them under `category`, which makes
    detection store the recurring payment the draft comes from."""
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        for month in (7, 8, 9):
            conn.execute(
                """
                INSERT INTO transactions (
                    source, account, booking_date, value_date, amount_cents, currency,
                    counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                    fingerprint, occurrence, category
                ) VALUES ('test', 'acc', ?, ?, -10000, 'EUR', 'Car Bank', '', NULL, 'M-1',
                          NULL, 'raw', ?, 1, NULL)
                """,
                (f"2026-0{month}-05", f"2026-0{month}-05", f"car{month}"),
            )
        if category is not None:
            add_rule(conn, TODAY, {"category": category, "counterparty": "Car Bank"})
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "t.db"
    _seed_car(path)
    return path


def _client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path, today=_today), follow_redirects=False)


def _stored_debts(db_path: Path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return list_debts(conn)
    finally:
        conn.close()


def _draft_id(page) -> int:
    return int(page.select_one("[data-draft-id]")["data-draft-id"])


def test_flagged_payment_shows_a_needs_details_card(db_path):
    with _client(db_path) as client:
        page = soup(client.get("/debts"))

    [card] = page.select("#debt-drafts [data-draft-id]")
    assert card.select_one('[data-badge="needs-details"]') is not None
    assert fields(card) == {
        "name": "Car Bank",
        "rate": 10_000,
        "every": "1 month(s)",
        "first_payment": "2026-07-05",
        "match": "mandate: M-1",
    }


def test_forms_are_prefilled_from_the_draft(db_path):
    with _client(db_path) as client:
        page = soup(client.get("/debts"))

    draft_id = _draft_id(page)
    installment = page.select_one(f"#complete-installment-{draft_id}")
    assert installment["action"] == f"/debts/drafts/{draft_id}/installment"
    values = {i["name"]: i["value"] for i in installment.select("input")}
    assert values == {
        "name": "Car Bank",
        "total": "",
        "rate": "100.00",
        "interval_months": "1",
        "first_payment_date": "2026-07-05",
        "payments_count": "",
        "match_value": "M-1",
    }
    assert installment.select_one("select[name=match_field] option[selected]")["value"] == "mandate"

    loan = page.select_one(f"#complete-loan-{draft_id}")
    assert loan["action"] == f"/debts/drafts/{draft_id}/loan"
    values = {i["name"]: i["value"] for i in loan.select("input")}
    assert values == {
        "name": "Car Bank",
        "balance": "",
        "balance_as_of": "",
        "rate": "100.00",
        "interest": "",
        "match_value": "M-1",
    }
    assert loan.select_one("select[name=match_field] option[selected]")["value"] == "mandate"


def test_draft_forms_offer_purpose_as_a_match_field(db_path):
    with _client(db_path) as client:
        page = soup(client.get("/debts"))

    draft_id = _draft_id(page)
    for form in (f"#complete-installment-{draft_id}", f"#complete-loan-{draft_id}"):
        options = [o["value"] for o in page.select(f"{form} select[name=match_field] option")]
        assert options == ["counterparty", "mandate", "purpose"]


def test_field_ids_are_unique_in_the_drafts_section(db_path):
    with _client(db_path) as client:
        page = soup(client.get("/debts"))

    # The add forms below reuse "field-<name>" ids across the two kinds, as before.
    ids = [el["id"] for el in page.select("#debt-drafts [id]")]
    assert len(ids) == len(set(ids))


def test_forms_start_closed(db_path):
    with _client(db_path) as client:
        page = soup(client.get("/debts"))

    details = page.select("#debt-drafts details")
    assert len(details) == 2
    assert not any(d.has_attr("open") for d in details)


def test_no_flagged_payment_shows_no_drafts_section(tmp_path):
    db_path = tmp_path / "t.db"
    _seed_car(db_path, category=None)

    with _client(db_path) as client:
        page = soup(client.get("/debts"))

    assert page.select_one("#debt-drafts") is None
    assert page.select("[data-draft-id]") == []


def _debt_names(page) -> list[str]:
    return [text(c.select_one('[data-field="name"]')) for c in page.select("[data-debt-id]")]


def test_completing_as_installment_creates_the_debt(db_path):
    with _client(db_path) as client:
        draft_id = _draft_id(soup(client.get("/debts")))
        data = {**VALID_INSTALLMENT, "name": "Car", "total": "1200.00", "payments_count": "12"}
        response = client.post(f"/debts/drafts/{draft_id}/installment", data=data)
        assert response.status_code == 303
        assert response.headers["location"] == "/debts"

        page = soup(client.get("/debts"))
        assert _debt_names(page) == ["Car"]
        [card] = page.select('[data-debt-id][data-kind="installment"]')
        assert fields(card)["total"] == 120_000
        assert page.select("[data-draft-id]") == []
        assert page.select_one("#debt-drafts") is None
        # A reload must not bring the draft back.
        assert soup(client.get("/debts")).select("[data-draft-id]") == []
    assert len(_stored_debts(db_path)) == 1


def test_completing_as_loan_creates_the_debt(db_path):
    with _client(db_path) as client:
        draft_id = _draft_id(soup(client.get("/debts")))
        response = client.post(f"/debts/drafts/{draft_id}/loan", data=VALID_LOAN)
        assert response.status_code == 303
        assert response.headers["location"] == "/debts"

        page = soup(client.get("/debts"))
        [card] = page.select('[data-debt-id][data-kind="loan"]')
        assert fields(card)["balance"] == 500_000
        assert fields(card)["as_of"] == "2026-06-30"
        assert page.select("[data-draft-id]") == []
        assert soup(client.get("/debts")).select("[data-draft-id]") == []
    assert len(_stored_debts(db_path)) == 1


@pytest.mark.parametrize(
    "kind,valid,field,bad",
    [
        ("installment", VALID_INSTALLMENT, "payments_count", "0"),
        ("installment", VALID_INSTALLMENT, "total", "abc"),
        ("loan", VALID_LOAN, "balance", "abc"),
        ("loan", VALID_LOAN, "balance_as_of", ""),
    ],
)
def test_bad_field_is_a_400_in_that_drafts_form(db_path, kind, valid, field, bad):
    with _client(db_path) as client:
        draft_id = _draft_id(soup(client.get("/debts")))
        data = {**valid, "name": "Typed name", field: bad}
        response = client.post(f"/debts/drafts/{draft_id}/{kind}", data=data)

    assert response.status_code == 400
    page = soup(response)
    form = page.select_one(f"#complete-{kind}-{draft_id}")
    alert = form.select_one("[data-draft-error]")
    assert alert["role"] == "alert"
    assert text(alert)
    assert form.select_one('input[name="name"]')["value"] == "Typed name"
    assert form.select_one(f'input[name="{field}"]')["value"] == bad
    assert form.find_parent("details").has_attr("open")
    other = "loan" if kind == "installment" else "installment"
    assert (
        not page.select_one(f"#complete-{other}-{draft_id}").find_parent("details").has_attr("open")
    )
    assert page.select_one("#form-error") is None
    assert len(page.select(f"[data-draft-id='{draft_id}']")) == 1
    assert _stored_debts(db_path) == []


@pytest.mark.parametrize("kind,valid", [("installment", VALID_INSTALLMENT), ("loan", VALID_LOAN)])
def test_completed_draft_is_404_and_adds_no_debt(db_path, kind, valid):
    with _client(db_path) as client:
        draft_id = _draft_id(soup(client.get("/debts")))
        assert client.post(f"/debts/drafts/{draft_id}/{kind}", data=valid).status_code == 303
        response = client.post(f"/debts/drafts/{draft_id}/{kind}", data=valid)

    assert response.status_code == 404
    assert f"No such draft: {draft_id}" in response.text
    assert len(_stored_debts(db_path)) == 1


@pytest.mark.parametrize("kind,valid", [("installment", VALID_INSTALLMENT), ("loan", VALID_LOAN)])
def test_unknown_draft_is_404_and_adds_no_debt(db_path, kind, valid):
    with _client(db_path) as client:
        response = client.post(f"/debts/drafts/999/{kind}", data=valid)

    assert response.status_code == 404
    assert "No such draft: 999" in response.text
    assert _stored_debts(db_path) == []
