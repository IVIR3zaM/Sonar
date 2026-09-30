"""Tests for the Fixed payments page (SPEC §6): plain HTML forms, water example end to end."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.recurring.schedule import occurrences
from sonar.recurring.store import list_payments
from sonar.web.app import _format_cents, create_app
from tests.html import cents, fields, soup
from tests.seed import seed

TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _payment_id(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        [payment] = list_payments(conn)
        return payment.id
    finally:
        conn.close()


def _payment_rows(response) -> list:
    return soup(response).select("#payments [data-payment-id]")


def _periods(row) -> list[tuple[list[str], int]]:
    """Each period's dates (start, then until if set) and amount in cents."""
    return [
        ([time["datetime"] for time in period.select("time")], cents(period))
        for period in row.select("[data-period]")
    ]


def test_water_example_end_to_end_via_forms(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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
        assert soup(page).select_one('a[href="/recurring"]') is not None
        assert soup(page).select_one("form#add-payment")["action"] == "/recurring"
        [row] = _payment_rows(page)
        assert int(row["data-payment-id"]) == payment_id
        shown = fields(row)
        assert shown["name"] == "Water"
        assert shown["amount"] == 26_000
        assert shown["last_paid"] == ""
        assert shown["next_due"] == "2026-11-15"
        assert _periods(row) == [
            (["2025-11-15", "2026-11-30"], 24_000),
            (["2027-02-01"], 26_000),
        ]

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

        edited = client.post(
            f"/recurring/{payment_id}/edit",
            follow_redirects=False,
            data={"name": "Fitness Studio", "amount": "55.00", "interval_months": "1", "day": "1"},
        )
        assert edited.status_code == 303

    # A fresh app instance simulates a restart against the same database.
    with TestClient(create_app(db_path, today=_today)) as client:
        conn = sqlite3.connect(db_path)
        try:
            [payment] = list_payments(conn)
        finally:
            conn.close()
        assert payment.name == "Fitness Studio"
        assert payment.periods[-1].amount_cents == 5500

        [row] = _payment_rows(client.get("/recurring"))
        assert fields(row)["name"] == "Fitness Studio"
        assert fields(row)["amount"] == 5_500


def test_dismiss_removes_from_page_and_stays_dismissed_after_restart(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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
        assert len(_payment_rows(client.get("/recurring"))) == 1

        dismissed = client.post(f"/recurring/{payment_id}/dismiss", follow_redirects=False)
        assert dismissed.status_code == 303

        assert _payment_rows(client.get("/recurring")) == []

    with TestClient(create_app(db_path, today=_today)) as client:
        assert _payment_rows(client.get("/recurring")) == []


def test_bad_amount_returns_400_and_stores_nothing(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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
    seed(db_path)

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
    with TestClient(create_app(db_path, today=_today)) as client:
        page = client.get("/recurring")
        assert page.status_code == 200
        [row] = _payment_rows(page)
        assert fields(row)["name"] == "Test Payment"
        assert fields(row)["last_paid"] == "2026-09-01"


def test_resume_with_empty_day_defaults_to_starts_on_day(tmp_path):
    """Resume posted with day="" defaults day to starts_on day."""
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
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


def test_row_shows_cadence_confirm_and_prefilled_edit_amount(tmp_path):
    """SPEC §12: compact row with cadence text, a confirm on dismiss, the edit
    amount input prefilled with `money`, and the displayed amount carrying
    data-cents."""
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        client.post(
            "/recurring",
            data={
                "name": "Quarterly Insurance",
                "amount": "180.00",
                "interval_months": "3",
                "day": "15",
                "starts_on": "2026-06-15",
            },
        )
        payment_id = _payment_id(db_path)

        [row] = _payment_rows(client.get("/recurring"))

        cadence_cell = row.select_one('[data-field="cadence"]')
        assert cadence_cell is not None
        assert cadence_cell.get_text(strip=True) == "every 3 mo · day 15"

        amount_cell = row.select_one('[data-field="amount"]')
        assert cents(amount_cell) == 18_000

        dismiss_form = row.select_one('form[action$="/dismiss"]')
        assert dismiss_form is not None
        assert "confirm(" in dismiss_form.get("onsubmit", "")

        edit_amount_input = row.select_one(f'input[id="edit-amount-payment-{payment_id}"]')
        assert edit_amount_input is not None
        assert edit_amount_input["value"] == _format_cents(18_000)

        # SPEC §12: every row shares a sign in this table, so red/green everywhere
        # would be noise; amount(..., colored=false) keeps data-cents but drops
        # the tone class.
        amount_span = amount_cell.select_one("[data-cents]")
        assert "text-negative" not in amount_span.get("class", [])
        assert "text-positive" not in amount_span.get("class", [])


def test_drawer_colspan_matches_header_count(tmp_path):
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
        page = soup(client.get("/recurring"))
        header_count = len(page.select("#payments thead th"))
        [drawer] = page.select("#payments [data-drawer-for]")
        assert int(drawer.select_one("td")["colspan"]) == header_count


def test_get_shows_all_drawers_hidden_and_toggle_script(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        for name in ("Gym", "Rent"):
            client.post(
                "/recurring",
                data={
                    "name": name,
                    "amount": "50.00",
                    "interval_months": "1",
                    "day": "1",
                    "starts_on": "2026-01-01",
                },
            )
        page = soup(client.get("/recurring"))
        drawers = page.select("#payments [data-drawer-for]")
        assert len(drawers) == 2
        assert all(drawer.has_attr("hidden") for drawer in drawers)
        # Two toggles per row (SPEC §12): the desktop "Edit" button in the
        # Manage cell, and an icon-only one in the Amount cell for mobile,
        # where Manage is hidden.
        toggles = page.select("[data-drawer-toggle]")
        assert len(toggles) == 4
        assert all(toggle["aria-expanded"] == "false" for toggle in toggles)

        script = "".join(tag.get_text() for tag in page.select("script"))
        assert "data-drawer-toggle" in script


def test_mobile_row_fits(tmp_path):
    """SPEC §12: no horizontal scroll at 375px. Below sm, only Name and Amount
    stay visible; Category/Cadence/Last paid/Next due/Manage collapse, and the
    Amount cell repeats the next due date plus an icon-only drawer toggle."""
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
        response = client.get("/recurring")
        [row] = _payment_rows(response)
        payment_id = int(row["data-payment-id"])

        page = soup(response)
        header_count = len(page.select("#payments thead th"))
        cells = row.select_one("tr[data-row]").select("td")
        assert len(cells) == header_count

        # Name and Amount are the only tds without the hidden-below-sm classes.
        for field, cell in zip(
            ("name", "category", "amount", "cadence", "last_paid", "next_due"),
            cells[:6],
            strict=True,
        ):
            classes = cell.get("class", [])
            hidden = "hidden" in classes and "sm:table-cell" in classes
            assert hidden == (field not in ("name", "amount")), field
        manage_cell = cells[-1]
        assert "hidden" in manage_cell.get("class", [])
        assert "sm:table-cell" in manage_cell.get("class", [])

        # Two toggles: the icon-only mobile one lives in the Amount cell, the
        # desktop "Edit" one in the (now hidden-below-sm) Manage cell.
        toggles = row.select("[data-drawer-toggle]")
        assert len(toggles) == 2
        amount_cell = cells[2]
        mobile_toggle = amount_cell.select_one("[data-drawer-toggle]")
        assert mobile_toggle is not None
        assert mobile_toggle["aria-label"] == "Edit Gym"
        assert manage_cell.select_one("[data-drawer-toggle]") is not None

        # The Amount cell repeats the next due date for mobile users.
        hidden_time = row.select_one('[data-field="next_due"] time')
        mobile_time = amount_cell.select_one("time")
        assert mobile_time is not None
        assert mobile_time["datetime"] == hidden_time["datetime"]

        drawer = page.select_one(f"#drawer-{payment_id}")
        assert int(drawer.select_one("td")["colspan"]) == header_count
