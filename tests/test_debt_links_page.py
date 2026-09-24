"""Tests linking a detected recurring payment to a debt (SPEC §7): the link
shows on both the Fixed payments page and the Installments and loans page,
and disappears from /debts once the recurring payment is dismissed.
"""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import MIGRATIONS_DIR, create_app
from sonar.db import apply_migrations
from sonar.recurring import dismiss, list_payments

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
    mandate_ref: str | None = None,
    creditor_id: str | None = None,
    amount_cents: int = -10_000,
) -> None:
    """Seed one debit directly by SQL, ready for the app's own startup
    reapply+sync (mirrors tests/test_recurring_refresh.py)."""
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        conn.execute(
            """
            INSERT INTO transactions (
                source, account, booking_date, value_date, amount_cents, currency,
                counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                fingerprint, occurrence, category
            ) VALUES (
                'test', 'acc', ?, ?, ?, 'EUR', ?, '', NULL, ?, ?, 'raw', ?, 1, NULL
            )
            """,
            (
                booking_date,
                booking_date,
                amount_cents,
                counterparty,
                mandate_ref,
                creditor_id,
                fingerprint,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_debt_link_shown_on_recurring_page_and_removed_from_debts_on_dismiss(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = _empty_categories(tmp_path)

    # Loan payment series: mandate M-1, creditor CRED -> detection key "mandate:CRED/M-1".
    for i, booking_date in enumerate(["2026-07-05", "2026-08-05", "2026-09-05"]):
        _insert_debit(
            db_path,
            fingerprint=f"loan{i}",
            booking_date=booking_date,
            counterparty="Auto Finance",
            mandate_ref="M-1",
            creditor_id="CRED",
        )
    # An unrelated series that no debt matches.
    for i, booking_date in enumerate(["2026-07-10", "2026-08-10", "2026-09-10"]):
        _insert_debit(
            db_path,
            fingerprint=f"gym{i}",
            booking_date=booking_date,
            counterparty="Fake Gym",
            amount_cents=-5_000,
        )

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        # Startup already ran reapply_rules + sync_detected, so both series are stored.
        add_response = client.post(
            "/debts/loans",
            follow_redirects=False,
            data={
                "name": "Car loan",
                "balance": "5000.00",
                "balance_as_of": "2026-06-30",
                "rate": "1000.00",
                "interest": "",
                "match_field": "mandate",
                "match_value": "M-1",
            },
        )
        assert add_response.status_code == 303

        recurring_text = client.get("/recurring").text
        assert "Debt: Car loan" in recurring_text
        assert recurring_text.count("Debt:") == 1  # the gym row shows no debt link

        debts_text = client.get("/debts").text
        assert "Auto Finance" in debts_text  # the detected payment's name, in the loan row

        conn = sqlite3.connect(db_path)
        try:
            [loan_payment] = [
                p for p in list_payments(conn) if p.detection_key == "mandate:CRED/M-1"
            ]
            dismiss(conn, loan_payment.id)
        finally:
            conn.close()

        debts_text_after_dismiss = client.get("/debts").text
        assert "Auto Finance" not in debts_text_after_dismiss
