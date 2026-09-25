"""Tests for taxonomy_service (SPEC §5, §13): the DB re-apply used by the app and CLI."""

import sqlite3
from datetime import date

from sonar.taxonomy_service import reapply_stored_taxonomy
from tests.seed import seed

TODAY = date(2026, 9, 23)

FITNESS_TOML = """
[[category]]
name = "Fitness"
type = "fixed"

[[rule]]
category = "Fitness"
counterparty = "Fake Gym"
"""


def _insert(
    conn: sqlite3.Connection, *, fingerprint: str, booking_date: str, counterparty: str
) -> None:
    conn.execute(
        """
        INSERT INTO transactions (
            source, account, booking_date, value_date, amount_cents, currency,
            counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
            fingerprint, occurrence, category
        ) VALUES (
            'test', 'acc', ?, ?, -5000, 'EUR', ?, '', NULL, NULL, NULL, 'raw', ?, 1, NULL
        )
        """,
        (booking_date, booking_date, counterparty, fingerprint),
    )
    conn.commit()


def test_reapply_categorizes_matching_rows_and_detects_a_monthly_fixed_series(tmp_path):
    db_path = tmp_path / "t.db"
    seed(db_path, FITNESS_TOML)

    conn = sqlite3.connect(db_path)
    try:
        for i, booking_date in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
            _insert(conn, fingerprint=f"gym{i}", booking_date=booking_date, counterparty="Fake Gym")
        _insert(conn, fingerprint="shop1", booking_date="2026-09-05", counterparty="Random Shop")

        uncategorized = reapply_stored_taxonomy(conn, TODAY)

        assert uncategorized == 1
        categories = dict(conn.execute("SELECT fingerprint, category FROM transactions").fetchall())
        assert categories["gym0"] == categories["gym1"] == categories["gym2"] == "Fitness"
        assert categories["shop1"] is None
        (payment_count,) = conn.execute("SELECT COUNT(*) FROM recurring_payments").fetchone()
        assert payment_count == 1
    finally:
        conn.close()
