"""Tests for the JSON API's recurring-payment endpoints (SPEC §6, §13): N02."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.auth.settings import AuthSettings
from sonar.db import connect
from sonar.recurring.schedule import SchedulePeriod
from sonar.recurring.store import add_manual, dismiss, get_payment
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
        response = client.put(f"/api/recurring/{payment_id}", json={"amount_cents": 1})

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
