"""Tests for the Fixed payments page (SPEC §6): plain HTML forms, water example end to end."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import MIGRATIONS_DIR, create_app
from sonar.db import apply_migrations
from sonar.recurring import list_payments
from sonar.schedule import occurrences

TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


def _payment_id(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        [payment] = list_payments(conn)
        return payment.id
    finally:
        conn.close()


def test_water_example_end_to_end_via_forms(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        add = client.post(
            "/recurring",
            follow_redirects=False,
            data={
                "name": "Water",
                "amount": "240.00",
                "interval_months": "2",
                "day": "15",
                "starts_on": "2025-11-15",
            },
        )
        assert add.status_code == 303
        payment_id = _payment_id(db_path)

        paused = client.post(
            f"/recurring/{payment_id}/pause",
            follow_redirects=False,
            data={"last_date": "2026-11-30"},
        )
        assert paused.status_code == 303

        resumed = client.post(
            f"/recurring/{payment_id}/resume",
            follow_redirects=False,
            data={
                "starts_on": "2027-02-01",
                "amount": "260.00",
                "interval_months": "2",
                "day": "15",
            },
        )
        assert resumed.status_code == 303

        page = client.get("/recurring")
        assert page.status_code == 200
        assert "Next due" in page.text
        assert "Last paid" in page.text
        assert 'href="/recurring"' in page.text
        assert "2026-11-15" in page.text
        assert "2025-11-15" in page.text
        assert "2026-11-30" in page.text
        assert "2027-02-01" in page.text
        assert "240.00" in page.text
        assert "260.00" in page.text

        conn = sqlite3.connect(db_path)
        try:
            [payment] = list_payments(conn)
        finally:
            conn.close()

        found = occurrences(payment.periods, date(2026, 9, 1), date(2027, 5, 31))
        due_dates = [o.due_date for o in found]
        assert due_dates == [
            date(2026, 9, 15),
            date(2026, 11, 15),
            date(2027, 2, 15),
            date(2027, 4, 15),
        ]
        assert [o.amount_cents for o in found] == [24000, 24000, 26000, 26000]
        assert all(d.month not in (12, 1) for d in due_dates)


def test_edit_survives_restart(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post(
            "/recurring",
            data={
                "name": "Gym",
                "amount": "50.00",
                "interval_months": "1",
                "day": "1",
                "starts_on": "2026-01-01",
            },
        )
        payment_id = _payment_id(db_path)

        edited = client.post(
            f"/recurring/{payment_id}/edit",
            follow_redirects=False,
            data={"name": "Fitness Studio", "amount": "55.00", "interval_months": "1", "day": "1"},
        )
        assert edited.status_code == 303

    # A fresh app instance simulates a restart against the same database.
    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        conn = sqlite3.connect(db_path)
        try:
            [payment] = list_payments(conn)
        finally:
            conn.close()
        assert payment.name == "Fitness Studio"
        assert payment.periods[-1].amount_cents == 5500

        page = client.get("/recurring")
        assert "Fitness Studio" in page.text
        assert "55.00" in page.text


def test_dismiss_removes_from_page_and_stays_dismissed_after_restart(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post(
            "/recurring",
            data={
                "name": "Streaming",
                "amount": "12.99",
                "interval_months": "1",
                "day": "5",
                "starts_on": "2026-01-05",
            },
        )
        payment_id = _payment_id(db_path)

        dismissed = client.post(f"/recurring/{payment_id}/dismiss", follow_redirects=False)
        assert dismissed.status_code == 303

        page = client.get("/recurring")
        assert "Streaming" not in page.text

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        page = client.get("/recurring")
        assert "Streaming" not in page.text


def test_bad_amount_returns_400_and_stores_nothing(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        response = client.post(
            "/recurring",
            data={
                "name": "Broken",
                "amount": "not-a-number",
                "interval_months": "1",
                "day": "1",
                "starts_on": "2026-01-01",
            },
        )
        assert response.status_code == 400

        conn = sqlite3.connect(db_path)
        try:
            assert list_payments(conn) == []
        finally:
            conn.close()


def test_detected_payment_shows_last_paid_date(tmp_path):
    """Insert a detected row by SQL and verify GET /recurring shows last_paid_date."""
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    # Apply migrations and insert a detected payment row directly into the database.
    # Use a NULL detection_key (manual-style) to avoid sync_detected deleting it.
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        cursor = conn.execute(
            """
            INSERT INTO recurring_payments
            (detection_key, name, category, status, source, last_paid_date)
            VALUES (NULL, 'Test Payment', NULL, 'active', 'detected', '2026-09-01')
            """
        )
        payment_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO schedule_periods (payment_id, starts_on, amount_cents, interval_months, day)
            VALUES (?, '2026-01-15', 50000, 1, 15)
            """,
            (payment_id,),
        )
        conn.commit()
    finally:
        conn.close()

    # Verify the page shows the last_paid_date.
    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        page = client.get("/recurring")
        assert page.status_code == 200
        assert "2026-09-01" in page.text
        assert "Test Payment" in page.text


def test_resume_with_empty_day_defaults_to_starts_on_day(tmp_path):
    """Resume posted with day="" defaults day to starts_on day."""
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        # Add a payment first.
        client.post(
            "/recurring",
            data={
                "name": "Paused Payment",
                "amount": "100.00",
                "interval_months": "1",
                "day": "5",
                "starts_on": "2026-01-05",
            },
        )
        payment_id = _payment_id(db_path)

        # Pause it.
        client.post(
            f"/recurring/{payment_id}/pause",
            follow_redirects=False,
            data={"last_date": "2026-08-31"},
        )

        # Resume with day="" (empty), starts_on "2027-02-10".
        # The day should default to 10 (the day of starts_on).
        response = client.post(
            f"/recurring/{payment_id}/resume",
            follow_redirects=False,
            data={
                "starts_on": "2027-02-10",
                "amount": "150.00",
                "interval_months": "1",
                "day": "",
            },
        )
        assert response.status_code == 303

        # Verify the new latest period has day == 10.
        conn = sqlite3.connect(db_path)
        try:
            [payment] = list_payments(conn)
            latest_period = payment.periods[-1]
            assert latest_period.day == 10
        finally:
            conn.close()
