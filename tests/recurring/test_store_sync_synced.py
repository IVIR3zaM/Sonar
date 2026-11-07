import sqlite3
from datetime import date

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.recurring.store import list_payments, sync_detected


def test_sync_keeps_payment_id_when_synced_debits_continue_a_mandate():
    with sqlite3.connect(":memory:") as conn:
        apply_migrations(conn, MIGRATIONS_DIR)

        def insert(month: int, amount: int, mandate: str | None):
            booked = date(2026, month, 14).isoformat()
            conn.execute(
                """INSERT INTO transactions (
                    source, account, booking_date, value_date, amount_cents, currency,
                    counterparty, purpose, iban, mandate_ref, creditor_id, raw_row,
                    fingerprint, occurrence, category
                ) VALUES ('test', 'test', ?, ?, ?, 'EUR', 'Example Utility', '',
                          'DE00 1111 2222 3333 4444 55', ?, ?, '', ?, 1, 'Utilities')""",
                (booked, booked, -amount, mandate, "CREDITOR" if mandate else None, booked),
            )

        for month in (5, 6, 7):
            insert(month, 1999, "MANDATE-A")
        sync_detected(conn, {"Utilities": "fixed"}, date(2026, 7, 15))
        [before] = list_payments(conn)

        for month in (8, 9):
            insert(month, 2199, None)
        sync_detected(conn, {"Utilities": "fixed"}, date(2026, 9, 15))
        [after] = list_payments(conn)

        assert after.id == before.id
        assert after.detection_key == "mandate:CREDITOR/MANDATE-A"
        assert after.last_paid_date == date(2026, 9, 14)
        assert after.periods[-1].amount_cents == 2199
