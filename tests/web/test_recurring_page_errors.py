"""Tests for error handling on the Fixed payments routes (SPEC §6, §12): 400 vs
404 and the friendly re-render.

Input validation (bad amount/interval/day/date) must return 400 before any
database write, with an inline #form-error alert inside the failing form and
the submitted values kept. An unknown payment id must return 404, rendered
as the styled error page (PaymentNotFound from recurring/store.py), not a crash.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonar.recurring.store import list_payments
from sonar.web.app import create_app
from tests.html import soup, text
from tests.seed import seed

TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _payment_id(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        [payment] = list_payments(conn)
        return payment.id
    finally:
        conn.close()


def _periods(db_path: Path, payment_id: int | None = None):
    conn = sqlite3.connect(db_path)
    try:
        payments = list_payments(conn)
        if payment_id is None:
            [payment] = payments
        else:
            [payment] = [p for p in payments if p.id == payment_id]
        return payment.periods
    finally:
        conn.close()


def _periods_or_empty(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        return list_payments(conn)
    finally:
        conn.close()


def _row(page, payment_id: int):
    """The <tbody> for a payment: the data row plus its drawer row."""
    row = page.select_one(f'tbody[data-payment-id="{payment_id}"]')
    assert row is not None, f"no row for payment {payment_id}"
    return row


def _drawer(page, payment_id: int):
    drawer = page.select_one(f"#drawer-{payment_id}")
    assert drawer is not None, f"no drawer for payment {payment_id}"
    return drawer


def _toggles(page, payment_id: int):
    """A row has two toggles (SPEC §12): the desktop Manage-cell one and the
    icon-only mobile one in the Amount cell; both must move together."""
    toggles = page.select(f'[data-drawer-toggle][aria-controls="drawer-{payment_id}"]')
    assert len(toggles) == 2, f"expected 2 drawer toggles for payment {payment_id}"
    return toggles


def _assert_only_drawer_open(page, open_id: int, other_id: int):
    """SPEC §12: an error re-render unhides only the failing row's drawer;
    every other row stays exactly as a fresh GET would render it."""
    opened = _drawer(page, open_id)
    assert opened.has_attr("hidden") is False
    assert opened.select_one("#form-error") is not None
    assert all(toggle["aria-expanded"] == "true" for toggle in _toggles(page, open_id))

    closed = _drawer(page, other_id)
    assert closed.has_attr("hidden") is True
    assert all(toggle["aria-expanded"] == "false" for toggle in _toggles(page, other_id))


def test_invalid_input_returns_400_and_leaves_payment_unchanged(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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
        client.post(
            "/recurring",
            data={
                "name": "Rent",
                "amount": "500.00",
                "interval_months": "1",
                "day": "1",
                "starts_on": "2026-01-01",
            },
        )
        conn = sqlite3.connect(db_path)
        try:
            gym_id, other_id = (p.id for p in list_payments(conn))
        finally:
            conn.close()
        payment_id = gym_id
        before = _periods(db_path, payment_id)

        # Test invalid interval_months in edit
        edited_bad_interval = client.post(
            f"/recurring/{payment_id}/edit",
            data={"name": "Gym", "amount": "50.00", "interval_months": "0", "day": "1"},
        )
        assert edited_bad_interval.status_code == 400
        assert _periods(db_path, payment_id) == before
        page = soup(edited_bad_interval)
        row = _row(page, payment_id)
        edit_form = row.select_one('form[action$="/edit"]')
        assert edit_form.select_one("#form-error")["role"] == "alert"
        assert edit_form.select_one('input[name="interval_months"]')["value"] == "0"
        assert edit_form.select_one('input[name="name"]')["value"] == "Gym"
        _assert_only_drawer_open(page, payment_id, other_id)

        # Test invalid day in edit
        edited_bad_day = client.post(
            f"/recurring/{payment_id}/edit",
            data={"name": "Gym", "amount": "50.00", "interval_months": "1", "day": "32"},
        )
        assert edited_bad_day.status_code == 400
        assert _periods(db_path, payment_id) == before
        page = soup(edited_bad_day)
        row = _row(page, payment_id)
        edit_form = row.select_one('form[action$="/edit"]')
        assert edit_form.select_one("#form-error") is not None
        assert edit_form.select_one('input[name="day"]')["value"] == "32"
        _assert_only_drawer_open(page, payment_id, other_id)

        paused = client.post(
            f"/recurring/{payment_id}/pause",
            data={"last_date": "2026-13-01"},
        )
        assert paused.status_code == 400
        assert _periods(db_path, payment_id) == before
        page = soup(paused)
        row = _row(page, payment_id)
        pause_form = row.select_one('form[action$="/pause"]')
        assert pause_form.select_one("#form-error")["role"] == "alert"
        assert pause_form.select_one('input[name="last_date"]')["value"] == "2026-13-01"
        _assert_only_drawer_open(page, payment_id, other_id)

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
        assert _periods(db_path, payment_id) == before
        page = soup(resumed_bad_starts)
        row = _row(page, payment_id)
        resume_form = row.select_one('form[action$="/resume"]')
        assert resume_form.select_one("#form-error") is not None
        assert resume_form.select_one('input[name="starts_on"]')["value"] == "not-a-date"
        _assert_only_drawer_open(page, payment_id, other_id)

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
        assert _periods(db_path, payment_id) == before

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
        assert _periods(db_path, payment_id) == before

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
        assert _periods(db_path, payment_id) == before

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
        assert _periods(db_path, payment_id) == before


def test_add_payment_invalid_input_returns_400_with_form_error_and_kept_values(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        response = client.post(
            "/recurring",
            data={
                "name": "Gym",
                "amount": "50.00",
                "interval_months": "0",
                "day": "1",
                "starts_on": "2026-01-01",
            },
        )

    assert response.status_code == 400
    page = soup(response)
    add_form = page.select_one("#add-payment")
    assert add_form.select_one("#form-error")["role"] == "alert"
    assert add_form.select_one('input[name="name"]')["value"] == "Gym"
    assert add_form.select_one('input[name="interval_months"]')["value"] == "0"
    assert _periods_or_empty(db_path) == []


def test_unknown_id_returns_404_on_edit_dismiss_pause_resume(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        edited = client.post(
            "/recurring/999/edit",
            data={"name": "Ghost", "amount": "10.00", "interval_months": "1", "day": "1"},
        )
        assert edited.status_code == 404
        assert soup(edited).select_one("#error-page") is not None

        dismissed = client.post("/recurring/999/dismiss")
        assert dismissed.status_code == 404
        assert soup(dismissed).select_one("#error-page") is not None

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


# (action, form data, the exact #form-error text SPEC §12 expects). Domain
# checks (interval/day range) get a full-sentence message naming the field;
# a malformed field (bad amount/date format) gets "<Label>: <hint>".
ROW_FRIENDLY_CASES = [
    (
        "edit",
        {"name": "Gym", "amount": "50.00", "interval_months": "0", "day": "1"},
        "Interval must be at least 1 month.",
    ),
    (
        "edit",
        {"name": "Gym", "amount": "50.00", "interval_months": "1", "day": "32"},
        "Day must be between 1 and 31.",
    ),
    (
        "edit",
        {"name": "Gym", "amount": "abc", "interval_months": "1", "day": "1"},
        "Amount: enter a number like 1234.56 or -250.50",
    ),
    (
        "pause",
        {"last_date": "2026-13-01"},
        "Ends/pauses after: pick a date",
    ),
    (
        "resume",
        {"starts_on": "not-a-date", "amount": "50.00", "interval_months": "1", "day": "1"},
        "Resumes on: pick a date",
    ),
    (
        "resume",
        {"starts_on": "2026-10-01", "amount": "50.00", "interval_months": "x", "day": "1"},
        "Every (months): enter a whole number",
    ),
]


@pytest.mark.parametrize("action,data,expected", ROW_FRIENDLY_CASES)
def test_row_error_message_is_friendly(tmp_path, action, data, expected):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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

        response = client.post(f"/recurring/{payment_id}/{action}", data=data)

    assert response.status_code == 400
    page = soup(response)
    alert = _drawer(page, payment_id).select_one("#form-error")
    assert text(alert) == expected
    assert alert["tabindex"] == "-1"
    assert "got " not in text(alert)
    assert "Invalid" not in text(alert)
    assert "_" not in text(alert)


def test_add_payment_error_message_is_friendly(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        response = client.post(
            "/recurring",
            data={
                "name": "Gym",
                "amount": "50.00",
                "interval_months": "0",
                "day": "1",
                "starts_on": "2026-01-01",
            },
        )

    assert response.status_code == 400
    page = soup(response)
    alert = page.select_one("#add-payment #form-error")
    assert text(alert) == "Interval must be at least 1 month."
    assert alert["tabindex"] == "-1"


def test_add_error_re_render_keeps_the_typed_description(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        response = client.post(
            "/recurring",
            data={
                "name": "Gym",
                "amount": "50.00",
                "interval_months": "0",
                "day": "1",
                "starts_on": "2026-01-01",
                "description": "Main studio",
            },
        )

    assert response.status_code == 400
    add_form = soup(response).select_one("#add-payment")
    assert add_form.select_one('input[name="description"]')["value"] == "Main studio"


def test_edit_error_re_render_keeps_the_typed_description(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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
        response = client.post(
            f"/recurring/{payment_id}/edit",
            data={
                "name": "Gym",
                "amount": "50.00",
                "interval_months": "0",
                "day": "1",
                "description": "Typed note",
            },
        )

    assert response.status_code == 400
    drawer = _drawer(soup(response), payment_id)
    assert drawer.select_one('input[name="description"]')["value"] == "Typed note"
