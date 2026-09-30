"""Tests for the Installments and loans page (SPEC §7): plain HTML forms, happy paths.

Expected cents/dates come from the T2/T3/T5 worked examples in the plan or are
computed here through debts/amortization.py directly, never copied from page output.
"""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import create_app
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.debts import amortization
from sonar.debts.store import list_debts
from tests.html import cents, fields, soup
from tests.seed import seed

TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _insert_debit(
    db_path: Path,
    *,
    fingerprint: str,
    booking_date: str,
    counterparty: str,
    amount_cents: int,
    mandate_ref: str | None = None,
) -> None:
    """Seed one debit transaction directly by SQL (the page reads stored rows)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO transactions (
                source, account, booking_date, value_date, amount_cents, currency,
                counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                fingerprint, occurrence, category
            ) VALUES (
                'test', 'acc', ?, ?, ?, 'EUR', ?, '', NULL, ?, NULL, 'raw', ?, 1, NULL
            )
            """,
            (booking_date, booking_date, amount_cents, counterparty, mandate_ref, fingerprint),
        )
        conn.commit()
    finally:
        conn.close()


def _cards(response) -> list:
    """Every debt card element ([data-debt-id]), in page order."""
    return soup(response).select("[data-debt-id]")


def _debts(response) -> dict[str, dict[str, int | str]]:
    """Every debt's shown fields, keyed by name."""
    shown = [fields(debt) for debt in _cards(response)]
    return {debt["name"]: debt for debt in shown}


def _card(response, name: str):
    [card] = [c for c in _cards(response) if fields(c)["name"] == name]
    return card


def _paid_percent(paid_cents: int, whole_cents: int) -> int:
    """Same round-half-up-then-clamp formula as debts.html's paid_percent macro."""
    raw = (200 * paid_cents + whole_cents) // (2 * whole_cents)
    return max(min(raw, 100), 0)


def _debt_id(db_path: Path, name: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        [stored] = [d for d in list_debts(conn) if d.debt.name == name]
        return stored.id
    finally:
        conn.close()


def test_debts_page_shows_installments_loans_and_total(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        # Sofa installment (T2 worked example): 3 matched debits plus one too
        # early (before first_payment_date - TOLERANCE) that must not count.
        for i, booking_date in enumerate(["2026-01-05", "2026-02-05", "2026-03-05"]):
            _insert_debit(
                db_path,
                fingerprint=f"sofa{i}",
                booking_date=booking_date,
                counterparty="Sofa Shop",
                amount_cents=-10_000,
            )
        _insert_debit(
            db_path,
            fingerprint="sofa-early",
            booking_date="2025-12-01",
            counterparty="Sofa Shop",
            amount_cents=-10_000,
        )
        assert (
            client.post(
                "/debts/installments",
                follow_redirects=False,
                data={
                    "name": "Sofa",
                    "total": "1200.00",
                    "rate": "100.00",
                    "interval_months": "1",
                    "first_payment_date": "2026-01-05",
                    "payments_count": "12",
                    "match_field": "counterparty",
                    "match_value": "Sofa Shop",
                },
            ).status_code
            == 303
        )

        # A paid-off installment: one payment covers the whole total.
        _insert_debit(
            db_path,
            fingerprint="paidoff",
            booking_date="2026-01-10",
            counterparty="Paid Shop",
            amount_cents=-5_000,
        )
        assert (
            client.post(
                "/debts/installments",
                follow_redirects=False,
                data={
                    "name": "Fully Paid",
                    "total": "50.00",
                    "rate": "50.00",
                    "interval_months": "1",
                    "first_payment_date": "2026-01-10",
                    "payments_count": "1",
                    "match_field": "counterparty",
                    "match_value": "Paid Shop",
                },
            ).status_code
            == 303
        )

        # Linear loan (T5 worked example): 500000 as of 2026-06-30, rate 100000.
        assert (
            client.post(
                "/debts/loans",
                follow_redirects=False,
                data={
                    "name": "Car loan",
                    "balance": "5000.00",
                    "balance_as_of": "2026-06-30",
                    "rate": "1000.00",
                    "interest": "",
                    "match_field": "mandate",
                    "match_value": "CAR-1",
                },
            ).status_code
            == 303
        )

        # 6.00% loan.
        assert (
            client.post(
                "/debts/loans",
                follow_redirects=False,
                data={
                    "name": "Mortgage",
                    "balance": "10000.00",
                    "balance_as_of": "2026-08-15",
                    "rate": "1000.00",
                    "interest": "6.00%",
                    "match_field": "mandate",
                    "match_value": "MORT-1",
                },
            ).status_code
            == 303
        )

        # 12.00% loan whose rate never outpaces the interest: never pays off.
        assert (
            client.post(
                "/debts/loans",
                follow_redirects=False,
                data={
                    "name": "Credit card",
                    "balance": "10000.00",
                    "balance_as_of": "2026-08-15",
                    "rate": "100.00",
                    "interest": "12.00%",
                    "match_field": "mandate",
                    "match_value": "CC-1",
                },
            ).status_code
            == 303
        )

        # Paid-off linear loan: rate 500.00 clears the 1000.00 balance in two
        # payments, no OLD-1 debits are seeded.
        assert (
            client.post(
                "/debts/loans",
                follow_redirects=False,
                data={
                    "name": "Old loan",
                    "balance": "1000.00",
                    "balance_as_of": "2026-01-15",
                    "rate": "500.00",
                    "interest": "",
                    "match_field": "mandate",
                    "match_value": "OLD-1",
                },
            ).status_code
            == 303
        )

        # CAR-1 debits: one before the statement date (must not count towards
        # "paid since statement"), one after (must count).
        _insert_debit(
            db_path,
            fingerprint="car-early",
            booking_date="2026-06-15",
            counterparty="Car Loan Co",
            amount_cents=-100_000,
            mandate_ref="CAR-1",
        )
        _insert_debit(
            db_path,
            fingerprint="car-payment",
            booking_date="2026-07-30",
            counterparty="Car Loan Co",
            amount_cents=-100_000,
            mandate_ref="CAR-1",
        )

        page = client.get("/debts")
        assert page.status_code == 200
        html = soup(page)
        debts = _debts(page)

        assert html.select_one('a[href="/debts"]') is not None  # nav link added to base.html
        assert html.select_one("form#add-installment")["action"] == "/debts/installments"
        assert html.select_one("form#add-loan")["action"] == "/debts/loans"

        assert debts["Sofa"] == {
            "name": "Sofa",
            "rate": 10_000,
            "every": "1 month(s)",
            "total": 120_000,
            "paid": 30_000,
            "remaining": 90_000,
            "payments_left": "9",
            "end_date": "2026-12-05",
            "match": "counterparty: Sofa Shop",
            "linked": "",
        }
        assert debts["Fully Paid"] == {
            "name": "Fully Paid",
            "rate": 5_000,
            "every": "1 month(s)",
            "total": 5_000,
            "paid": 5_000,
            "remaining": 0,
            "payments_left": "0",
            "end_date": "2026-01-10",
            "match": "counterparty: Paid Shop",
            "linked": "",
        }

        # Progress bar: aria-valuenow is the paid share of the total, rounded
        # half up and clamped to [0, 100] (paid_percent in debts.html).
        sofa_bar = _card(page, "Sofa").select_one('[role="progressbar"]')
        assert sofa_bar["aria-valuenow"] == str(_paid_percent(30_000, 120_000))
        assert _card(page, "Sofa").select_one('[data-badge="paid-off"]') is None

        fully_paid_bar = _card(page, "Fully Paid").select_one('[role="progressbar"]')
        assert fully_paid_bar["aria-valuenow"] == str(_paid_percent(5_000, 5_000)) == "100"
        assert _card(page, "Fully Paid").select_one('[data-badge="paid-off"]') is not None

        # Delete asks for confirmation before submitting.
        sofa_delete = _card(page, "Sofa").select_one("form")
        assert "confirm(" in sofa_delete["onsubmit"]

        # Linear loan: expected values from debts/amortization.py directly.
        car_schedule = amortization.loan_schedule(500_000, date(2026, 6, 30), 100_000, None)
        car_projected = amortization.balance_on(500_000, car_schedule, TODAY)
        car_payoff = amortization.payoff_date(car_schedule)
        assert car_projected == 300_000
        assert car_payoff == date(2026, 11, 30)
        assert debts["Car loan"] == {
            "name": "Car loan",
            "balance": 500_000,
            "as_of": "2026-06-30",
            "rate": 100_000,
            "interest": "linear",
            "projected": car_projected,
            "payoff": car_payoff.isoformat(),
            "paid_since": 100_000,
            "match": "mandate: CAR-1",
            "linked": "",
        }
        car_bar = _card(page, "Car loan").select_one('[role="progressbar"]')
        assert car_bar["aria-valuenow"] == str(_paid_percent(500_000 - car_projected, 500_000))
        assert _card(page, "Car loan").select_one('[data-badge="paid-off"]') is None

        # 6.00% loan: expected values from debts/amortization.py directly.
        interest_schedule = amortization.loan_schedule(1_000_000, date(2026, 8, 15), 100_000, 600)
        expected_projected = amortization.balance_on(1_000_000, interest_schedule, TODAY)
        expected_payoff = amortization.payoff_date(interest_schedule)
        assert expected_projected == 905_000
        assert expected_payoff is not None
        assert debts["Mortgage"] == {
            "name": "Mortgage",
            "balance": 1_000_000,
            "as_of": "2026-08-15",
            "rate": 100_000,
            "interest": "6.00%",
            "projected": expected_projected,
            "payoff": expected_payoff.isoformat(),
            "paid_since": 0,
            "match": "mandate: MORT-1",
            "linked": "",
        }

        # 12.00% loan whose rate never outpaces the interest: never pays off.
        never_schedule = amortization.loan_schedule(1_000_000, date(2026, 8, 15), 10_000, 1200)
        assert amortization.payoff_date(never_schedule) is None
        never_projected = amortization.balance_on(1_000_000, never_schedule, TODAY)
        assert never_projected == 1_000_000
        assert debts["Credit card"] == {
            "name": "Credit card",
            "balance": 1_000_000,
            "as_of": "2026-08-15",
            "rate": 10_000,
            "interest": "12.00%",
            "projected": never_projected,
            "payoff": "never",
            "paid_since": 0,
            "match": "mandate: CC-1",
            "linked": "",
        }
        assert _card(page, "Credit card").select_one('[data-badge="paid-off"]') is None

        # Paid-off linear loan: payments 2026-02-15 leave 50_000, 2026-03-15
        # leaves 0.
        old_schedule = amortization.loan_schedule(100_000, date(2026, 1, 15), 50_000, None)
        assert amortization.payoff_date(old_schedule) == date(2026, 3, 15)
        assert amortization.balance_on(100_000, old_schedule, TODAY) == 0
        assert debts["Old loan"] == {
            "name": "Old loan",
            "balance": 100_000,
            "as_of": "2026-01-15",
            "rate": 50_000,
            "interest": "linear",
            "projected": 0,
            "payoff": "2026-03-15",
            "paid_since": 0,
            "match": "mandate: OLD-1",
            "linked": "",
        }
        old_bar = _card(page, "Old loan").select_one('[role="progressbar"]')
        assert old_bar["aria-valuenow"] == "100"
        assert _card(page, "Old loan").select_one('[data-badge="paid-off"]') is not None
        assert len(debts) == 6

        # Total remaining = installment remaining (Sofa 900.00 + Fully Paid 0)
        # plus every loan's projected balance (linear + 6% + 12% + the
        # paid-off loan, which adds 0).
        total_remaining_cents = 90_000 + 0 + car_projected + expected_projected + never_projected
        assert total_remaining_cents == 2_295_000
        assert cents(html.select_one("#debts-total")) == total_remaining_cents

        # Delete removes the row.
        fully_paid_id = _debt_id(db_path, "Fully Paid")
        deleted = client.post(f"/debts/{fully_paid_id}/delete", follow_redirects=False)
        assert deleted.status_code == 303
        assert "Fully Paid" not in _debts(client.get("/debts"))


def test_bad_installment_field_returns_400_and_stores_nothing(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        response = client.post(
            "/debts/installments",
            data={
                "name": "Broken",
                "total": "100.00",
                "rate": "10.00",
                "interval_months": "0",  # invalid: must be >= 1
                "first_payment_date": "2026-01-05",
                "payments_count": "12",
                "match_field": "counterparty",
                "match_value": "Shop",
            },
        )
        assert response.status_code == 400

        conn = sqlite3.connect(db_path)
        try:
            apply_migrations(conn, MIGRATIONS_DIR)
            assert list_debts(conn) == []
        finally:
            conn.close()


def test_delete_unknown_debt_returns_404(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path)

    with TestClient(create_app(db_path, today=_today)) as client:
        response = client.post("/debts/999/delete")
        assert response.status_code == 404
