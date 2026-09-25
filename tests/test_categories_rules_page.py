"""Tests for the Rules card on the Categories page (SPEC §5, §12): N09.

Category CRUD is covered by test_categories_page.py; this file covers rule
add/edit/delete/move, chips, and friendly errors.
"""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations, connect
from tests.html import soup, text

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 23)

# The example IBAN from the IBAN Wikipedia page, the only one allowed in tests.
EXAMPLE_IBAN = "DE89 3704 0044 0532 0130 00"


def _fresh_app(tmp_path: Path):
    # Only the 0006 migration's generic seed (Groceries, Housing, Donations,
    # ...): rules are added through the page itself in these tests.
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()
    return create_app(db_path, today=lambda: TODAY), db_path


def _insert(
    conn: sqlite3.Connection,
    *,
    fingerprint: str,
    counterparty: str,
    amount_cents: int = -5000,
    iban: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', '2026-09-05', '2026-09-05', ?, 'EUR', ?, '', ?,
            NULL, NULL, 'raw', ?, 1, NULL
        )
        """,
        (amount_cents, counterparty, iban, fingerprint),
    )
    conn.commit()


def _uncategorized_count(client: TestClient) -> int:
    page = soup(client.get("/uncategorized"))
    return int(text(page.select_one("#uncategorized-count")))


def _rule_id(db_path: Path, category: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            """
            SELECT r.id FROM category_rules r JOIN categories c ON c.id = r.category_id
            WHERE c.name = ?
            """,
            (category,),
        ).fetchone()[0]
    finally:
        conn.close()


def test_add_rule_categorizes_matching_row_and_drops_uncategorized_count(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="m1", counterparty="Testmarkt Filiale 12")
    finally:
        conn.close()

    with TestClient(app) as client:
        before = _uncategorized_count(client)

        response = client.post(
            "/categories/rules",
            data={"category": "Groceries", "counterparty": "testmarkt"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/categories#rules"

        after = _uncategorized_count(client)
        assert after == before - 1

        page = soup(client.get("/categories"))
        rows = page.select("[data-rule-id]")
        assert len(rows) == 1
        assert rows[0]["data-position"] == "1"
        assert "Groceries" in text(rows[0])


def test_second_rule_at_position_1_wins_then_moving_it_down_restores_the_first(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="m1", counterparty="Testmarkt Filiale 12")
    finally:
        conn.close()

    with TestClient(app) as client:
        client.post(
            "/categories/rules", data={"category": "Groceries", "counterparty": "testmarkt"}
        )
        client.post(
            "/categories/rules",
            data={"category": "Dining", "counterparty": "testmarkt", "position": "1"},
        )

        conn = sqlite3.connect(db_path)
        try:
            category = conn.execute(
                "SELECT category FROM transactions WHERE fingerprint = 'm1'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert category == "Dining"

        dining_id = _rule_id(db_path, "Dining")
        response = client.post(
            f"/categories/rules/{dining_id}/move", data={"position": "2"}, follow_redirects=False
        )
        assert response.status_code == 303

        conn = sqlite3.connect(db_path)
        try:
            category = conn.execute(
                "SELECT category FROM transactions WHERE fingerprint = 'm1'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert category == "Groceries"

        page = soup(client.get("/categories"))
        rows = page.select("[data-rule-id]")
        assert [r["data-position"] for r in rows] == ["1", "2"]


def test_edit_rule_changes_category(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/categories/rules", data={"category": "Groceries", "counterparty": "testmarkt"}
        )
        rule_id = _rule_id(db_path, "Groceries")

        response = client.post(
            f"/categories/rules/{rule_id}/edit",
            data={"category": "Dining", "counterparty": "testmarkt"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = soup(client.get("/categories"))
        row = page.select_one(f'[data-rule-id="{rule_id}"]')
        assert "Dining" in text(row)


def test_delete_rule_removes_it_and_uncategorizes_the_row_again(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="m1", counterparty="Testmarkt Filiale 12")
    finally:
        conn.close()

    with TestClient(app) as client:
        client.post(
            "/categories/rules", data={"category": "Groceries", "counterparty": "testmarkt"}
        )
        before = _uncategorized_count(client)
        rule_id = _rule_id(db_path, "Groceries")

        response = client.post(f"/categories/rules/{rule_id}/delete", follow_redirects=False)
        assert response.status_code == 303

        after = _uncategorized_count(client)
        assert after == before + 1

        page = soup(client.get("/categories"))
        assert page.select_one(f'[data-rule-id="{rule_id}"]') is None


def test_iban_rule_typed_with_spaces_and_lowercase_matches(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(
            conn,
            fingerprint="m1",
            counterparty="Fake Payee",
            iban=EXAMPLE_IBAN.replace(" ", ""),
        )
    finally:
        conn.close()

    with TestClient(app) as client:
        response = client.post(
            "/categories/rules",
            data={
                "category": "Groceries",
                "counterparty": "Fake Payee",
                "iban": EXAMPLE_IBAN.lower(),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    conn = sqlite3.connect(db_path)
    try:
        category = conn.execute(
            "SELECT category FROM transactions WHERE fingerprint = 'm1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert category == "Groceries"


def test_amount_range_matches_within_bounds_only(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="in_range", counterparty="Fake Payee A", amount_cents=-2500)
        _insert(conn, fingerprint="out_of_range", counterparty="Fake Payee A", amount_cents=-6000)
    finally:
        conn.close()

    with TestClient(app) as client:
        response = client.post(
            "/categories/rules",
            data={
                "category": "Groceries",
                "counterparty": "Fake Payee A",
                "min_amount": "10.00",
                "max_amount": "50.00",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    conn = sqlite3.connect(db_path)
    try:
        categories = dict(conn.execute("SELECT fingerprint, category FROM transactions").fetchall())
    finally:
        conn.close()
    assert categories["in_range"] == "Groceries"
    assert categories["out_of_range"] is None


def test_bad_regex_no_text_unknown_category_and_min_above_max_return_400(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/categories/rules",
            data={"category": "Groceries", "counterparty_regex": "("},
        )
        assert response.status_code == 400
        page = soup(response)
        assert text(page.select_one("#form-error")) == "Counterparty regex is not a valid pattern."
        assert page.select_one('#add-rule-form select[name="category"]') is not None

        response = client.post("/categories/rules", data={"category": "Groceries"})
        assert response.status_code == 400
        page = soup(response)
        assert (
            text(page.select_one("#form-error")) == "Enter a counterparty or purpose text or regex."
        )

        response = client.post(
            "/categories/rules", data={"category": "Nope", "counterparty": "Fake Payee"}
        )
        assert response.status_code == 400
        page = soup(response)
        assert text(page.select_one("#form-error")) == "Unknown category: Nope."

        response = client.post(
            "/categories/rules",
            data={
                "category": "Groceries",
                "counterparty": "Fake Payee",
                "min_amount": "50.00",
                "max_amount": "10.00",
            },
        )
        assert response.status_code == 400
        page = soup(response)
        assert (
            text(page.select_one("#form-error"))
            == "Minimum amount must not be above maximum amount."
        )
        kept = page.select_one('#add-rule-form input[name="counterparty"]')
        assert kept["value"] == "Fake Payee"


def test_unknown_rule_id_returns_404(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        edit = client.post(
            "/categories/rules/999999/edit",
            data={"category": "Groceries", "counterparty": "Fake Payee"},
        )
        delete = client.post("/categories/rules/999999/delete")

    assert edit.status_code == 404
    assert delete.status_code == 404
