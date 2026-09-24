"""Tests for the Installments and loans page (SPEC §7): plain HTML forms, happy paths.

Expected cents/dates come from the T2/T3/T5 worked examples in the plan or are
computed here through amortization.py directly, never copied from page output.
"""

import re
import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar import amortization
from sonar.app import create_app
from sonar.db import apply_migrations
from sonar.debt_store import list_debts

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"
TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _empty_categories(tmp_path: Path) -> Path:
    path = tmp_path / "categories.toml"
    path.write_text("", encoding="utf-8")
    return path


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


def _row_cells(html: str, name: str) -> list[str]:
    """Cell texts of the <tr> whose first <td> is exactly `name`, minus Actions."""
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = [cell.strip() for cell in re.findall(r"<td>(.*?)</td>", row, re.S)]
        if cells and cells[0] == name:
            return cells[:-1]
    raise AssertionError(f"no row found for {name!r}")


def _debt_id(db_path: Path, name: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        [stored] = [d for d in list_debts(conn) if d.debt.name == name]
        return stored.id
    finally:
        conn.close()


def test_debts_page_shows_installments_loans_and_total(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
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
        text = page.text

        assert 'href="/debts"' in text  # nav link added to base.html

        # Installment columns: Name, Rate, Every, Total, Paid so far, Remaining,
        # Payments left, End date, Match, Linked payments, Status.
        assert _row_cells(text, "Sofa") == [
            "Sofa",
            "100.00",
            "1 month(s)",
            "1200.00",
            "300.00",
            "900.00",
            "9",
            "2026-12-05",
            "counterparty: Sofa Shop",
            "",
            "",
        ]
        assert _row_cells(text, "Fully Paid") == [
            "Fully Paid",
            "50.00",
            "1 month(s)",
            "50.00",
            "50.00",
            "0.00",
            "0",
            "2026-01-10",
            "counterparty: Paid Shop",
            "",
            "paid off",
        ]

        # Linear loan: expected values from amortization.py directly.
        car_schedule = amortization.loan_schedule(500_000, date(2026, 6, 30), 100_000, None)
        car_projected = amortization.balance_on(500_000, car_schedule, TODAY)
        car_payoff = amortization.payoff_date(car_schedule)
        assert car_projected == 300_000
        assert car_payoff == date(2026, 11, 30)
        # Loan columns: Name, Balance, As of, Monthly rate, Interest, Projected
        # balance, Payoff date, Paid since statement, Match, Linked, Status.
        assert _row_cells(text, "Car loan") == [
            "Car loan",
            "5000.00",
            "2026-06-30",
            "1000.00",
            "linear",
            "3000.00",
            "2026-11-30",
            "1000.00",
            "mandate: CAR-1",
            "",
            "",
        ]

        # 6.00% loan: expected values from amortization.py directly.
        interest_schedule = amortization.loan_schedule(1_000_000, date(2026, 8, 15), 100_000, 600)
        expected_projected = amortization.balance_on(1_000_000, interest_schedule, TODAY)
        expected_payoff = amortization.payoff_date(interest_schedule)
        assert expected_projected == 905_000
        assert expected_payoff is not None
        assert _row_cells(text, "Mortgage") == [
            "Mortgage",
            "10000.00",
            "2026-08-15",
            "1000.00",
            "6.00%",
            "9050.00",
            expected_payoff.isoformat(),
            "0.00",
            "mandate: MORT-1",
            "",
            "",
        ]

        # 12.00% loan whose rate never outpaces the interest: never pays off.
        never_schedule = amortization.loan_schedule(1_000_000, date(2026, 8, 15), 10_000, 1200)
        assert amortization.payoff_date(never_schedule) is None
        never_projected = amortization.balance_on(1_000_000, never_schedule, TODAY)
        assert never_projected == 1_000_000
        assert _row_cells(text, "Credit card") == [
            "Credit card",
            "10000.00",
            "2026-08-15",
            "100.00",
            "12.00%",
            "10000.00",
            "never",
            "0.00",
            "mandate: CC-1",
            "",
            "",
        ]

        # Paid-off linear loan: payments 2026-02-15 leave 50_000, 2026-03-15
        # leaves 0.
        old_schedule = amortization.loan_schedule(100_000, date(2026, 1, 15), 50_000, None)
        assert amortization.payoff_date(old_schedule) == date(2026, 3, 15)
        assert amortization.balance_on(100_000, old_schedule, TODAY) == 0
        assert _row_cells(text, "Old loan") == [
            "Old loan",
            "1000.00",
            "2026-01-15",
            "500.00",
            "linear",
            "0.00",
            "2026-03-15",
            "0.00",
            "mandate: OLD-1",
            "",
            "paid off",
        ]

        # Total remaining = installment remaining (Sofa 900.00 + Fully Paid 0)
        # plus every loan's projected balance (linear + 6% + 12% + the
        # paid-off loan, which adds 0).
        total_remaining_cents = 90_000 + 0 + car_projected + expected_projected + never_projected
        assert total_remaining_cents == 2_295_000
        assert "22950.00" in text

        # Delete removes the row.
        fully_paid_id = _debt_id(db_path, "Fully Paid")
        deleted = client.post(f"/debts/{fully_paid_id}/delete", follow_redirects=False)
        assert deleted.status_code == 303
        page_after_delete = client.get("/debts")
        assert "Fully Paid" not in page_after_delete.text


def test_bad_installment_field_returns_400_and_stores_nothing(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
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
    categories_path = _empty_categories(tmp_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        response = client.post("/debts/999/delete")
        assert response.status_code == 404
