"""Tests for error handling on the Fixed payments routes (SPEC §6): 400 vs 404.

Input validation (bad amount/interval/day/date) must return 400 before any
database write. An unknown payment id must return 404 (PaymentNotFound from
recurring.py), not crash.
"""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.recurring import list_payments

TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


def _payment_id(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        [payment] = list_payments(conn)
        return payment.id
    finally:
        conn.close()


def _periods(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        [payment] = list_payments(conn)
        return payment.periods
    finally:
        conn.close()


def test_invalid_input_returns_400_and_leaves_payment_unchanged(tmp_path):
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
        before = _periods(db_path)

        # Test invalid interval_months in edit
        edited_bad_interval = client.post(
            f"/recurring/{payment_id}/edit",
            data={"name": "Gym", "amount": "50.00", "interval_months": "0", "day": "1"},
        )
        assert edited_bad_interval.status_code == 400
        assert _periods(db_path) == before

        # Test invalid day in edit
        edited_bad_day = client.post(
            f"/recurring/{payment_id}/edit",
            data={"name": "Gym", "amount": "50.00", "interval_months": "1", "day": "32"},
        )
        assert edited_bad_day.status_code == 400
        assert _periods(db_path) == before

        paused = client.post(
            f"/recurring/{payment_id}/pause",
            data={"last_date": "2026-13-01"},
        )
        assert paused.status_code == 400
        assert _periods(db_path) == before

        resumed_bad_starts = client.post(
            f"/recurring/{payment_id}/resume",
            data={
                "starts_on": "not-a-date",
                "amount": "50.00",
                "interval_months": "1",
                "day": "1",
            },
        )
        assert resumed_bad_starts.status_code == 400
        assert _periods(db_path) == before

        resumed_bad_amount = client.post(
            f"/recurring/{payment_id}/resume",
            data={
                "starts_on": "2026-10-01",
                "amount": "-5",
                "interval_months": "1",
                "day": "1",
            },
        )
        assert resumed_bad_amount.status_code == 400
        assert _periods(db_path) == before

        resumed_bad_interval = client.post(
            f"/recurring/{payment_id}/resume",
            data={
                "starts_on": "2026-10-01",
                "amount": "50.00",
                "interval_months": "x",
                "day": "1",
            },
        )
        assert resumed_bad_interval.status_code == 400
        assert _periods(db_path) == before

        # Test invalid interval_months in resume
        resumed_bad_resume_interval = client.post(
            f"/recurring/{payment_id}/resume",
            data={
                "starts_on": "2026-10-01",
                "amount": "50.00",
                "interval_months": "0",
                "day": "1",
            },
        )
        assert resumed_bad_resume_interval.status_code == 400
        assert _periods(db_path) == before

        # Test invalid day in resume
        resumed_bad_resume_day = client.post(
            f"/recurring/{payment_id}/resume",
            data={
                "starts_on": "2026-10-01",
                "amount": "50.00",
                "interval_months": "1",
                "day": "32",
            },
        )
        assert resumed_bad_resume_day.status_code == 400
        assert _periods(db_path) == before


def test_unknown_id_returns_404_on_edit_dismiss_pause_resume(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        edited = client.post(
            "/recurring/999/edit",
            data={"name": "Ghost", "amount": "10.00", "interval_months": "1", "day": "1"},
        )
        assert edited.status_code == 404

        dismissed = client.post("/recurring/999/dismiss")
        assert dismissed.status_code == 404

        paused = client.post("/recurring/999/pause", data={"last_date": "2026-10-01"})
        assert paused.status_code == 404

        resumed = client.post(
            "/recurring/999/resume",
            data={
                "starts_on": "2026-10-01",
                "amount": "10.00",
                "interval_months": "1",
                "day": "1",
            },
        )
        assert resumed.status_code == 404
