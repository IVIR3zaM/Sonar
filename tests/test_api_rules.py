"""Tests for the JSON API's rule endpoints (SPEC §5, §13): N17."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import apply_migrations, connect

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 23)


def _fresh_app(tmp_path: Path):
    # Only the 0006 migration's generic seed (Groceries, Dining, ...): rules
    # are added through the API itself in these tests.
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
    finally:
        conn.close()
    return create_app(db_path, today=lambda: TODAY), db_path


def _insert(
    conn: sqlite3.Connection, *, fingerprint: str, counterparty: str, amount_cents: int = -5000
) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', '2026-09-05', '2026-09-05', ?, 'EUR', ?, 'card payment',
            NULL, NULL, NULL, 'raw', ?, 1, NULL
        )
        """,
        (amount_cents, counterparty, fingerprint),
    )
    conn.commit()


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


def _uncategorized_keys(client: TestClient) -> set[str]:
    body = client.get("/api/uncategorized").json()
    return {group["counterparty"] for group in body["groups"]}


def test_add_rule_categorizes_matching_row_and_drops_uncategorized(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="m1", counterparty="Testmarkt Filiale 12")
    finally:
        conn.close()

    with TestClient(app) as client:
        before = client.get("/api/uncategorized").json()["count"]
        assert "testmarkt filiale 12" in _uncategorized_keys(client)

        response = client.post(
            "/api/rules", json={"category": "Groceries", "counterparty": "testmarkt"}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["category"] == "Groceries"
        assert body["position"] == 1
        assert body["uncategorized"] == before - 1
        assert "testmarkt filiale 12" not in _uncategorized_keys(client)


def test_second_rule_at_position_1_wins_then_move_restores_the_first(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="m1", counterparty="Testmarkt Filiale 12")
    finally:
        conn.close()

    with TestClient(app) as client:
        client.post("/api/rules", json={"category": "Groceries", "counterparty": "testmarkt"})
        client.post(
            "/api/rules",
            json={"category": "Dining", "counterparty": "testmarkt", "position": 1},
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
        response = client.post(f"/api/rules/{dining_id}/move", json={"position": 2})

        assert response.status_code == 200
        rules = response.json()["rules"]
        assert [r["category"] for r in rules] == ["Groceries", "Dining"]

        conn = sqlite3.connect(db_path)
        try:
            category = conn.execute(
                "SELECT category FROM transactions WHERE fingerprint = 'm1'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert category == "Groceries"


def test_put_rule_changes_category(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/rules", json={"category": "Groceries", "counterparty": "testmarkt"})
        rule_id = _rule_id(db_path, "Groceries")

        response = client.put(
            f"/api/rules/{rule_id}", json={"category": "Dining", "counterparty": "testmarkt"}
        )

        assert response.status_code == 200
        assert response.json()["category"] == "Dining"


def test_delete_rule_puts_the_row_back_into_uncategorized(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="m1", counterparty="Testmarkt Filiale 12")
    finally:
        conn.close()

    with TestClient(app) as client:
        client.post("/api/rules", json={"category": "Groceries", "counterparty": "testmarkt"})
        rule_id = _rule_id(db_path, "Groceries")
        assert "testmarkt filiale 12" not in _uncategorized_keys(client)

        response = client.delete(f"/api/rules/{rule_id}")

        assert response.status_code == 200
        assert response.json()["category"] == "Groceries"
        assert "testmarkt filiale 12" in _uncategorized_keys(client)


def test_bad_regex_returns_400_with_purpose_regex_field_and_rules_unchanged(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        before = client.get("/api/rules").json()

        response = client.post("/api/rules", json={"category": "Groceries", "purpose_regex": "("})

        assert response.status_code == 400
        assert response.json()["field"] == "purpose_regex"
        assert client.get("/api/rules").json() == before


def test_unknown_json_field_returns_422(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/rules",
            json={"category": "Groceries", "counterparty": "testmarkt", "typo": "x"},
        )

    assert response.status_code == 422


def test_non_json_content_type_returns_415_and_changes_nothing(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        before = client.get("/api/rules").json()

        response = client.post(
            "/api/rules",
            content=b'{"category": "Groceries", "counterparty": "testmarkt"}',
            headers={"Content-Type": "text/plain"},
        )

        assert response.status_code == 415
        assert client.get("/api/rules").json() == before


def test_unknown_rule_id_returns_404_json(tmp_path):
    app, _ = _fresh_app(tmp_path)
    with TestClient(app) as client:
        put = client.put(
            "/api/rules/999999", json={"category": "Groceries", "counterparty": "testmarkt"}
        )
        delete = client.delete("/api/rules/999999")
        move = client.post("/api/rules/999999/move", json={"position": 1})

    assert put.status_code == 404
    assert delete.status_code == 404
    assert move.status_code == 404
    assert put.json()["error"] == "No such rule: 999999"


def test_uncategorized_groups_match_the_text_export(tmp_path):
    app, db_path = _fresh_app(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert(conn, fingerprint="m1", counterparty="Testmarkt Filiale 12")
        _insert(conn, fingerprint="m2", counterparty="Testmarkt Filiale 12")
        _insert(conn, fingerprint="m3", counterparty="Zebra Shop")
    finally:
        conn.close()

    with TestClient(app) as client:
        api_groups = client.get("/api/uncategorized").json()["groups"]
        page = client.get("/uncategorized")

    from tests.html import soup

    request_text = soup(page).select_one("#categorization-request").get_text()
    exported_lines = [line for line in request_text.splitlines() if "x " in line]

    assert [g["counterparty"] for g in api_groups] == [
        "testmarkt filiale 12",
        "zebra shop",
    ]
    assert len(exported_lines) == len(api_groups)
    for group, line in zip(api_groups, exported_lines, strict=True):
        assert line.startswith(f"{group['count']}x {group['counterparty']} |")
