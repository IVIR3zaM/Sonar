"""Tests wiring sync_detected into the app (SPEC §6): re-run detection like the rules."""

import sqlite3
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from sonar.app import MIGRATIONS_DIR, create_app
from sonar.db import apply_migrations
from sonar.recurring import dismiss, list_payments

FIXTURE = Path(__file__).parent / "fixtures" / "db_girokonto.csv"
FIXTURE_LINES = FIXTURE.read_text(encoding="utf-8-sig").splitlines()
PREAMBLE_AND_HEADER = FIXTURE_LINES[:8]  # lines 1-8: preamble + the 18-column header
FOOTER = FIXTURE_LINES[-1]  # "Account balance;9/23/2026;;;-448.43;EUR"

GYM_TOML = """
[[category]]
name = "Fitness"
type = "fixed"

[[rule]]
category = "Fitness"
counterparty = "Gym Inc"
"""

GYM_TOML_VARIABLE = """
[[category]]
name = "Fitness"
type = "variable"

[[rule]]
category = "Fitness"
counterparty = "Gym Inc"
"""

TODAY = date(2026, 9, 23)


def _today() -> date:
    return TODAY


def _monthly_debit_row(booking_date: str, counterparty: str = "Fake Gym") -> str:
    # Same 18-column layout as the fixture's data rows; only booking/value
    # date, counterparty, purpose and the Debit column are filled in.
    fields = [
        booking_date,
        booking_date,
        "Standing Order",
        counterparty,
        "Monthly fee",
        "",  # IBAN
        "",  # BIC
        "",  # Customer Reference
        "",  # Mandate Reference
        "",  # Creditor ID
        "",  # Compensation amount
        "",  # Original Amount
        "",  # Ultimate creditor
        "",  # Number of transactions
        "",  # Number of cheques
        "-50.00",  # Debit
        "",  # Credit
        "EUR",
    ]
    return ";".join(fields)


def _seed_gym_transactions(db_path: Path) -> None:
    """Insert a monthly series directly by SQL, ready for the app's own reapply+sync."""
    conn = sqlite3.connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
            conn.execute(
                """
                INSERT INTO transactions (
                    source, account, booking_date, value_date, amount_cents, currency,
                    counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                    fingerprint, occurrence, category
                ) VALUES (
                    'test', 'acc', ?, ?, -1000, 'EUR',
                    'Gym Inc', '', NULL, NULL, NULL, 'raw', ?, 1, NULL
                )
                """,
                (booking_date, booking_date, f"m{i}"),
            )
        conn.commit()
    finally:
        conn.close()


def _payment_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM recurring_payments").fetchone()
        return count
    finally:
        conn.close()


def test_lifespan_syncs_detected_payments_from_existing_rows(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text(GYM_TOML, encoding="utf-8")
    _seed_gym_transactions(db_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)):
        pass  # startup alone (lifespan) must reapply rules and sync detection

    assert _payment_count(db_path) == 1


def test_import_stores_detected_payment_and_reupload_keeps_one_row(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text("", encoding="utf-8")  # no rules needed: uncategorized counts too
    rows = [_monthly_debit_row(d) for d in ("7/23/2026", "8/23/2026", "9/23/2026")]
    content = "\n".join([*PREAMBLE_AND_HEADER, *rows, FOOTER]).encode("utf-8")

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])
        assert _payment_count(db_path) == 1

        # Re-uploading the same file adds 0 rows; detection must still see 1 payment.
        client.post("/import", files=[("files", ("giro.csv", content, "text/csv"))])
        assert _payment_count(db_path) == 1


def test_dismissed_payment_stays_dismissed_after_restart(tmp_path):
    db_path = tmp_path / "t.db"
    categories_path = tmp_path / "categories.toml"
    categories_path.write_text(GYM_TOML, encoding="utf-8")
    _seed_gym_transactions(db_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)):
        conn = sqlite3.connect(db_path)
        try:
            [payment] = list_payments(conn)
            dismiss(conn, payment.id)
        finally:
            conn.close()

    # A fresh app instance simulates a restart against the same database.
    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)):
        conn = sqlite3.connect(db_path)
        try:
            [still_dismissed] = list_payments(conn, include_dismissed=True)
        finally:
            conn.close()

    assert still_dismissed.status == "dismissed"


def test_reapply_reruns_detection_and_respects_category_type(tmp_path):
    """Test POST /reapply re-runs detection when category type changes."""
    db_path = tmp_path / "t.db"
    categories_path = tmp_path / "categories.toml"
    # The rule categorizes the gym debits as "Fitness", typed variable, so detection skips them.
    categories_path.write_text(GYM_TOML_VARIABLE, encoding="utf-8")
    _seed_gym_transactions(db_path)

    with TestClient(create_app(db_path, categories_path=categories_path, today=_today)) as client:
        # With gym as variable, detection should not store any payment
        assert _payment_count(db_path) == 0

        # Change the toml to have gym as fixed
        categories_path.write_text(GYM_TOML, encoding="utf-8")

        # POST /reapply to trigger re-detection
        response = client.post("/reapply")
        assert response.status_code == 200

        # Now the gym payment should be detected and stored
        assert _payment_count(db_path) == 1

        # Change the toml back to variable
        categories_path.write_text(GYM_TOML_VARIABLE, encoding="utf-8")

        # POST /reapply again
        response = client.post("/reapply")
        assert response.status_code == 200

        # The payment should be removed since gym is now variable again
        assert _payment_count(db_path) == 0
