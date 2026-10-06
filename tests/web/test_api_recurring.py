"""Tests for the JSON API's recurring-payment endpoints (SPEC §6, §13): N02."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.auth.settings import AuthSettings
from sonar.categorization.service import add_rule
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual, dismiss, get_payment, list_payments
from sonar.web.app import create_app
from tests.seed import seed

TODAY = date(2026, 9, 23)
TOKEN = "s3cret-token"
AUTH = AuthSettings(
    google_client_id="client-id",
    google_client_secret="client-secret",
    session_secret="session-secret",
    base_url="http://testserver",
    api_token=TOKEN,
)


def _app(tmp_path: Path, auth: AuthSettings | None = None):
    db_path = tmp_path / "t.db"
    seed(db_path)
    return create_app(db_path, today=lambda: TODAY, auth=auth), db_path


def _add(db_path: Path, name: str, amount_cents: int = 4500, day: int = 5) -> int:
    conn = connect(db_path)
    try:
        period = SchedulePeriod(date(2026, 1, 1), None, amount_cents, 1, day)
        return add_manual(conn, name, None, period)
    finally:
        conn.close()


def _stored(db_path: Path, payment_id: int):
    conn = connect(db_path)
    try:
        return get_payment(conn, payment_id)
    finally:
        conn.close()


def test_put_description_then_get_lists_it_with_the_schedule(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water", amount_cents=4500, day=5)
    with TestClient(app) as client:
        put = client.put(f"/api/recurring/{payment_id}", json={"description": "Tap water"})
        listed = client.get("/api/recurring")

    expected = {
        "id": payment_id,
        "detection_key": None,
        "name": "Water",
        "description": "Tap water",
        "category": None,
        "status": "active",
        "amount_cents": 4500,
        "interval_months": 1,
        "day": 5,
        "source": "manual",
        "last_paid_date": None,
        "next_due": "2026-10-05",
        "until": None,
        "periods": [
            {
                "starts_on": "2026-01-01",
                "until": None,
                "amount_cents": 4500,
                "interval_months": 1,
                "day": 5,
            }
        ],
        "debt_id": None,
    }
    assert put.status_code == 200
    assert put.json() == expected
    assert listed.status_code == 200
    assert listed.json() == [expected]


def test_get_lists_dismissed_payments_too(tmp_path):
    app, db_path = _app(tmp_path)
    kept = _add(db_path, "Water", day=5)
    gone = _add(db_path, "Gym", day=9)
    conn = connect(db_path)
    try:
        dismiss(conn, gone)
    finally:
        conn.close()
    with TestClient(app) as client:
        items = client.get("/api/recurring").json()

    assert [(item["id"], item["status"]) for item in items] == [
        (kept, "active"),
        (gone, "dismissed"),
    ]


def test_put_description_only_keeps_name_unlocked_and_periods_unchanged(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    conn = connect(db_path)
    try:
        conn.execute("UPDATE recurring_payments SET name_locked = 0 WHERE id = ?", (payment_id,))
        conn.commit()
    finally:
        conn.close()
    before = _stored(db_path, payment_id)
    with TestClient(app) as client:
        response = client.put(f"/api/recurring/{payment_id}", json={"description": "Tap water"})

    after = _stored(db_path, payment_id)
    assert response.status_code == 200
    assert after.name == "Water"
    assert after.name_locked is False
    assert after.periods == before.periods
    assert after.schedule_locked == before.schedule_locked


def test_put_name_changes_it_and_locks_it_and_keeps_the_description(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE recurring_payments SET name_locked = 0, description = 'Tap' WHERE id = ?",
            (payment_id,),
        )
        conn.commit()
    finally:
        conn.close()
    with TestClient(app) as client:
        response = client.put(f"/api/recurring/{payment_id}", json={"name": "Water bill"})

    stored = _stored(db_path, payment_id)
    assert response.status_code == 200
    assert response.json()["name"] == "Water bill"
    assert response.json()["description"] == "Tap"
    assert stored.name == "Water bill"
    assert stored.name_locked is True
    assert stored.description == "Tap"


def test_put_null_or_blank_description_clears_it(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        client.put(f"/api/recurring/{payment_id}", json={"description": "Tap"})
        cleared = client.put(f"/api/recurring/{payment_id}", json={"description": None})
        client.put(f"/api/recurring/{payment_id}", json={"description": "Tap"})
        blanked = client.put(f"/api/recurring/{payment_id}", json={"description": "   "})

    assert cleared.status_code == 200
    assert cleared.json()["description"] is None
    assert blanked.json()["description"] is None
    assert _stored(db_path, payment_id).description is None


def test_put_blank_name_answers_400_and_changes_nothing(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        response = client.put(
            f"/api/recurring/{payment_id}", json={"name": "  ", "description": "Tap"}
        )

    assert response.status_code == 400
    assert response.json()["field"] == "name"
    assert response.json()["error"]
    stored = _stored(db_path, payment_id)
    assert stored.name == "Water"
    assert stored.description is None


def test_put_unknown_key_answers_422(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        response = client.put(f"/api/recurring/{payment_id}", json={"colour": "red"})

    assert response.status_code == 422


def test_put_unknown_id_answers_404(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.put("/api/recurring/999", json={"description": "x"})

    assert response.status_code == 404
    assert response.json() == {"error": "No such recurring payment: 999"}


def test_with_sign_in_on_the_right_bearer_reaches_put_and_a_wrong_one_gets_401(tmp_path):
    app, db_path = _app(tmp_path, auth=AUTH)
    payment_id = _add(db_path, "Water")
    with TestClient(app, follow_redirects=False) as client:
        right = client.put(
            f"/api/recurring/{payment_id}",
            json={"description": "Tap"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        wrong = client.put(
            f"/api/recurring/{payment_id}",
            json={"description": "Nope"},
            headers={"Authorization": "Bearer wrong"},
        )

    assert right.status_code == 200
    assert right.json()["description"] == "Tap"
    assert wrong.status_code == 401
    assert _stored(db_path, payment_id).description == "Tap"


def test_post_dismiss_marks_the_payment_dismissed_and_get_lists_it(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water", amount_cents=4500, day=5)
    with TestClient(app) as client:
        response = client.post(f"/api/recurring/{payment_id}/dismiss")
        listed = client.get("/api/recurring")

    assert response.status_code == 200
    assert response.json()["id"] == payment_id
    assert response.json()["name"] == "Water"
    assert response.json()["amount_cents"] == 4500
    assert response.json()["status"] == "dismissed"
    assert [(item["id"], item["status"]) for item in listed.json()] == [(payment_id, "dismissed")]


def test_post_dismiss_on_a_dismissed_payment_answers_200_unchanged(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        first = client.post(f"/api/recurring/{payment_id}/dismiss")
        again = client.post(f"/api/recurring/{payment_id}/dismiss")

    assert again.status_code == 200
    assert again.json() == first.json()


def test_post_dismiss_unknown_id_answers_404(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/recurring/999/dismiss")

    assert response.status_code == 404
    assert response.json() == {"error": "No such recurring payment: 999"}


def test_with_sign_in_on_the_right_bearer_reaches_dismiss_and_a_wrong_one_gets_401(tmp_path):
    app, db_path = _app(tmp_path, auth=AUTH)
    kept = _add(db_path, "Water", day=5)
    gone = _add(db_path, "Gym", day=9)
    with TestClient(app, follow_redirects=False) as client:
        wrong = client.post(
            f"/api/recurring/{kept}/dismiss", headers={"Authorization": "Bearer wrong"}
        )
        right = client.post(
            f"/api/recurring/{gone}/dismiss", headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert wrong.status_code == 401
    assert _stored(db_path, kept).status == "active"
    assert right.status_code == 200
    assert right.json()["status"] == "dismissed"


NEW = {
    "name": "Gym",
    "amount_cents": 2500,
    "interval_months": 1,
    "day": 9,
    "starts_on": "2026-09-09",
}


def test_post_adds_a_manual_payment_and_get_lists_it_with_the_page_figures(tmp_path):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        posted = client.post("/api/recurring", json={**NEW, "name": " Gym ", "description": "Fit"})
        listed = client.get("/api/recurring")

    [item] = listed.json()
    assert posted.status_code == 201
    assert posted.json() == item
    assert item["name"] == "Gym"
    assert item["description"] == "Fit"
    assert item["source"] == "manual"
    assert item["next_due"] == "2026-10-09"
    assert item["until"] is None
    assert item["debt_id"] is None
    assert item["periods"] == [
        {
            "starts_on": "2026-09-09",
            "until": None,
            "amount_cents": 2500,
            "interval_months": 1,
            "day": 9,
        }
    ]
    assert _stored(db_path, item["id"]).schedule_locked is True


@pytest.mark.parametrize("key", list(NEW))
def test_post_missing_key_answers_400_naming_it(tmp_path, key):
    app, db_path = _app(tmp_path)
    body = {k: v for k, v in NEW.items() if k != key}
    with TestClient(app) as client:
        response = client.post("/api/recurring", json=body)

    assert response.status_code == 400
    assert response.json() == {"error": f"{key} is required", "field": key}
    assert _all_payments(db_path) == []


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"name": "   "}, "name"),
        ({"starts_on": "09/09/2026"}, "starts_on"),
        ({"amount_cents": 0}, "amount_cents"),
        ({"interval_months": 0}, "interval_months"),
        ({"day": 32}, "day"),
    ],
)
def test_post_invalid_value_answers_400_naming_the_field(tmp_path, change, field):
    app, db_path = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/recurring", json={**NEW, **change})

    assert response.status_code == 400
    assert response.json()["field"] == field
    assert response.json()["error"]
    assert _all_payments(db_path) == []


def test_post_text_in_amount_cents_answers_422(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/recurring", json={**NEW, "amount_cents": "25.00"})

    assert response.status_code == 422


def test_put_amount_only_locks_the_schedule_and_changes_only_that_value(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water", amount_cents=4500, day=5)
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE recurring_payments SET schedule_locked = 0 WHERE id = ?", (payment_id,)
        )
        conn.commit()
    finally:
        conn.close()
    before = _stored(db_path, payment_id).periods[-1]
    with TestClient(app) as client:
        response = client.put(f"/api/recurring/{payment_id}", json={"amount_cents": 5000})

    after = _stored(db_path, payment_id)
    assert response.status_code == 200
    assert response.json()["amount_cents"] == 5000
    assert after.schedule_locked is True
    assert after.periods[-1] == SchedulePeriod(
        before.starts_on, before.until, 5000, before.interval_months, before.day
    )


def test_put_invalid_schedule_value_answers_400_and_changes_nothing(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    before = _stored(db_path, payment_id)
    with TestClient(app) as client:
        response = client.put(f"/api/recurring/{payment_id}", json={"day": 32})

    assert response.status_code == 400
    assert response.json()["field"] == "day"
    assert _stored(db_path, payment_id) == before


def test_post_pause_sets_until_and_ends_the_schedule(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        response = client.post(
            f"/api/recurring/{payment_id}/pause", json={"last_date": "2026-09-30"}
        )

    assert response.status_code == 200
    assert response.json()["until"] == "2026-09-30"
    assert response.json()["periods"][-1]["until"] == "2026-09-30"
    assert response.json()["next_due"] is None
    assert _stored(db_path, payment_id).periods[-1].until == date(2026, 9, 30)


def test_post_pause_bad_or_missing_date_answers_400(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        bad = client.post(f"/api/recurring/{payment_id}/pause", json={"last_date": "soon"})
        missing = client.post(f"/api/recurring/{payment_id}/pause", json={})

    assert bad.status_code == 400
    assert bad.json()["field"] == "last_date"
    assert missing.status_code == 400
    assert missing.json() == {"error": "last_date is required", "field": "last_date"}


def test_post_resume_adds_a_period_and_day_defaults_to_the_start_day(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water", amount_cents=4500, day=5)
    with TestClient(app) as client:
        client.post(f"/api/recurring/{payment_id}/pause", json={"last_date": "2026-08-31"})
        response = client.post(
            f"/api/recurring/{payment_id}/resume",
            json={"starts_on": "2026-11-17", "amount_cents": 6000, "interval_months": 2},
        )

    body = response.json()
    assert response.status_code == 200
    assert [p["starts_on"] for p in body["periods"]] == ["2026-01-01", "2026-11-17"]
    assert body["periods"][-1] == {
        "starts_on": "2026-11-17",
        "until": None,
        "amount_cents": 6000,
        "interval_months": 2,
        "day": 17,
    }
    assert body["until"] is None
    assert body["amount_cents"] == 6000


def test_post_resume_with_a_day_uses_it_and_a_bad_value_answers_400(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    base = {"starts_on": "2026-11-17", "amount_cents": 6000, "interval_months": 1}
    with TestClient(app) as client:
        bad = client.post(f"/api/recurring/{payment_id}/resume", json={**base, "day": 0})
        missing = client.post(
            f"/api/recurring/{payment_id}/resume", json={"starts_on": "2026-11-17"}
        )
        good = client.post(f"/api/recurring/{payment_id}/resume", json={**base, "day": 3})

    assert bad.status_code == 400
    assert bad.json()["field"] == "day"
    assert missing.status_code == 400
    assert missing.json()["field"] == "amount_cents"
    assert good.json()["periods"][-1]["day"] == 3


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "pause", {"last_date": "2026-09-30"}),
        ("post", "resume", {"starts_on": "2026-11-17", "amount_cents": 1, "interval_months": 1}),
        ("put", "", {"amount_cents": 100}),
        ("post", "restore", None),
    ],
)
def test_unknown_id_answers_404_on_pause_resume_put_and_restore(tmp_path, method, path, body):
    app, _ = _app(tmp_path)
    url = f"/api/recurring/999/{path}".rstrip("/")
    with TestClient(app) as client:
        response = getattr(client, method)(url, **({} if body is None else {"json": body}))

    assert response.status_code == 404
    assert response.json() == {"error": "No such recurring payment: 999"}


def test_post_restore_makes_a_dismissed_payment_active_again(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        client.post(f"/api/recurring/{payment_id}/dismiss")
        response = client.post(f"/api/recurring/{payment_id}/restore")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert _stored(db_path, payment_id).status == "active"


def test_post_restore_on_an_active_payment_answers_409(tmp_path):
    app, db_path = _app(tmp_path)
    payment_id = _add(db_path, "Water")
    with TestClient(app) as client:
        response = client.post(f"/api/recurring/{payment_id}/restore")

    assert response.status_code == 409
    assert response.json() == {"error": f"Recurring payment {payment_id} is not dismissed"}


def test_debt_id_is_the_debt_that_links_the_payment(tmp_path):
    db_path = tmp_path / "t.db"
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
                ) VALUES ('test', 'acc', ?, ?, -10000, 'EUR', 'Car Bank', '', NULL, NULL,
                    NULL, 'raw', ?, 1, NULL)
                """,
                (f"2026-0{month}-05", f"2026-0{month}-05", f"car{month}"),
            )
        add_rule(conn, TODAY, {"category": "Loans & Installments", "counterparty": "Car Bank"})
        conn.commit()
    finally:
        conn.close()
    debt = {
        "kind": "installment",
        "name": "Car",
        "total_cents": 120_000,
        "rate_cents": 10_000,
        "interval_months": 1,
        "first_payment_date": "2026-07-05",
        "payments_count": 12,
        "match_field": "counterparty",
        "match_value": "Car Bank",
    }
    app = create_app(db_path, today=lambda: TODAY)
    with TestClient(app) as client:
        before = client.get("/api/recurring").json()
        debt_id = client.post("/api/debts", json=debt).json()["id"]
        after = client.get("/api/recurring").json()

    assert [item["debt_id"] for item in before] == [None]
    assert [item["debt_id"] for item in after] == [debt_id]


def _all_payments(db_path: Path):
    conn = connect(db_path)
    try:
        return list_payments(conn, include_dismissed=True)
    finally:
        conn.close()
