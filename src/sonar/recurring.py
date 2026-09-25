"""DB shell for recurring payments (SPEC §6): storage and manual corrections.

`schedule.py` holds the pure schedule-period logic. This module is the thin
shell around it: it stores a payment's schedule periods, lets the user edit,
pause, resume, dismiss and add payments, and locks whatever the user has
touched so detection (T6) never overwrites a correction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.categorizing import transactions_with_category
from sonar.recurrence import DetectedPayment, detect_recurring
from sonar.schedule import SchedulePeriod, pause_after, resume_on

_PAYMENT_COLUMNS = (
    "id, detection_key, name, category, status, source, "
    "name_locked, schedule_locked, last_paid_date"
)


class PaymentNotFound(LookupError):
    """Raised by edit/dismiss/pause/resume when `id` has no matching row."""


@dataclass(frozen=True)
class RecurringPayment:
    id: int
    detection_key: str | None
    name: str
    category: str | None
    status: str
    source: str
    name_locked: bool
    schedule_locked: bool
    last_paid_date: date | None
    periods: tuple[SchedulePeriod, ...]


def list_payments(
    conn: sqlite3.Connection, include_dismissed: bool = False
) -> list[RecurringPayment]:
    """All payments, ordered by the latest period's day then name."""
    query = f"SELECT {_PAYMENT_COLUMNS} FROM recurring_payments"
    if not include_dismissed:
        query += " WHERE status = 'active'"
    rows = conn.execute(query).fetchall()
    payments = [_payment_from_row(conn, row) for row in rows]
    return sorted(payments, key=lambda p: (_latest_period(p.periods).day, p.name))


def add_manual(
    conn: sqlite3.Connection, name: str, category: str | None, period: SchedulePeriod
) -> int:
    """Add a hand-entered payment; both locks are set since nothing was detected."""
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO recurring_payments (
                detection_key, name, category, status, source, name_locked, schedule_locked
            ) VALUES (NULL, ?, ?, 'active', 'manual', 1, 1)
            """,
            (name, category),
        )
        payment_id = cursor.lastrowid
        _insert_periods(conn, payment_id, (period,))
    return payment_id


def edit_payment(
    conn: sqlite3.Connection,
    id: int,
    name: str,
    amount_cents: int,
    interval_months: int,
    day: int,
) -> None:
    """Edit the name and the latest period in place, locking whatever changed."""
    with conn:
        row = conn.execute(
            "SELECT name, name_locked, schedule_locked FROM recurring_payments WHERE id = ?",
            (id,),
        ).fetchone()
        if row is None:
            raise PaymentNotFound(id)
        current_name, name_locked, schedule_locked = row
        periods = _load_periods(conn, id)
        latest = _latest_period(periods)

        name_changed = name != current_name
        schedule_changed = (
            amount_cents != latest.amount_cents
            or interval_months != latest.interval_months
            or day != latest.day
        )

        conn.execute(
            """
            UPDATE recurring_payments
            SET name = ?, name_locked = ?, schedule_locked = ?
            WHERE id = ?
            """,
            (name, name_locked or name_changed, schedule_locked or schedule_changed, id),
        )
        conn.execute(
            "UPDATE schedule_periods SET amount_cents = ?, interval_months = ?, day = ? "
            "WHERE payment_id = ? AND starts_on = ?",
            (amount_cents, interval_months, day, id, latest.starts_on.isoformat()),
        )


def dismiss(conn: sqlite3.Connection, id: int) -> None:
    with conn:
        _require_exists(conn, id)
        conn.execute("UPDATE recurring_payments SET status = 'dismissed' WHERE id = ?", (id,))


def pause_payment(conn: sqlite3.Connection, id: int, last_date: date) -> None:
    """Stop the schedule after `last_date` (SPEC §6, "ends or pauses after")."""
    with conn:
        _require_exists(conn, id)
        periods = _load_periods(conn, id)
        _replace_periods(conn, id, pause_after(periods, last_date))
        conn.execute("UPDATE recurring_payments SET schedule_locked = 1 WHERE id = ?", (id,))


def resume_payment(
    conn: sqlite3.Connection,
    id: int,
    starts_on: date,
    amount_cents: int,
    interval_months: int,
    day: int,
) -> None:
    """Start a new period from `starts_on` (SPEC §6, "resumes on <date> with amount X")."""
    with conn:
        _require_exists(conn, id)
        periods = _load_periods(conn, id)
        new_periods = resume_on(periods, starts_on, amount_cents, interval_months, day)
        _replace_periods(conn, id, new_periods)
        conn.execute("UPDATE recurring_payments SET schedule_locked = 1 WHERE id = ?", (id,))


def sync_detected(conn: sqlite3.Connection, category_types: dict[str, str], today: date) -> int:
    """Refresh detected payments from the stored transactions; return rows changed.

    My edits always win (SPEC §6): a dismissed row is left untouched so dismissals
    survive re-detection, and a locked name or schedule is kept as the user set it.
    A detected row that no longer matches anything is deleted, but only if it is
    still exactly as detection left it (active, unlocked) - an edited or dismissed
    row is kept even once its key stops being detected.
    """
    detected = {
        payment.key: payment
        for payment in detect_recurring(transactions_with_category(conn), category_types, today)
    }
    changed = 0
    with conn:
        existing = {
            key: (payment_id, status, bool(name_locked), bool(schedule_locked))
            for key, payment_id, status, name_locked, schedule_locked in conn.execute(
                "SELECT detection_key, id, status, name_locked, schedule_locked "
                "FROM recurring_payments WHERE detection_key IS NOT NULL"
            ).fetchall()
        }

        for key, payment in detected.items():
            if key not in existing:
                _insert_detected(conn, payment)
                changed += 1
                continue
            payment_id, status, name_locked, schedule_locked = existing[key]
            if status == "dismissed":
                continue  # leave dismissed rows alone; the user rejected this payment
            if _update_detected(conn, payment_id, payment, name_locked, schedule_locked):
                changed += 1

        for key in existing.keys() - detected.keys():
            payment_id, status, name_locked, schedule_locked = existing[key]
            if status == "active" and not name_locked and not schedule_locked:
                _delete_payment(conn, payment_id)
                changed += 1
    return changed


def _insert_detected(conn: sqlite3.Connection, payment: DetectedPayment) -> None:
    cursor = conn.execute(
        """
        INSERT INTO recurring_payments (
            detection_key, name, category, status, source,
            name_locked, schedule_locked, last_paid_date
        ) VALUES (?, ?, ?, 'active', 'detected', 0, 0, ?)
        """,
        (payment.key, payment.name, payment.category, payment.last_paid_date.isoformat()),
    )
    _insert_periods(conn, cursor.lastrowid, (payment.schedule,))


def _update_detected(
    conn: sqlite3.Connection,
    payment_id: int,
    payment: DetectedPayment,
    name_locked: bool,
    schedule_locked: bool,
) -> bool:
    current_name, current_category, current_last_paid = conn.execute(
        "SELECT name, category, last_paid_date FROM recurring_payments WHERE id = ?",
        (payment_id,),
    ).fetchone()
    new_name = current_name if name_locked else payment.name
    last_paid = payment.last_paid_date.isoformat()
    changed = (
        new_name != current_name
        or payment.category != current_category
        or last_paid != current_last_paid
    )
    # last_paid_date and category always reflect the latest detection run, even
    # when the name or schedule is locked and stays as the user set it.
    conn.execute(
        "UPDATE recurring_payments SET name = ?, category = ?, last_paid_date = ? WHERE id = ?",
        (new_name, payment.category, last_paid, payment_id),
    )
    if not schedule_locked:
        current_periods = _load_periods(conn, payment_id)
        if current_periods != (payment.schedule,):
            _replace_periods(conn, payment_id, (payment.schedule,))
            changed = True
    return changed


def _require_exists(conn: sqlite3.Connection, payment_id: int) -> None:
    row = conn.execute("SELECT 1 FROM recurring_payments WHERE id = ?", (payment_id,)).fetchone()
    if row is None:
        raise PaymentNotFound(payment_id)


def _delete_payment(conn: sqlite3.Connection, payment_id: int) -> None:
    # Foreign keys are off in db.connect, so periods must be deleted explicitly.
    conn.execute("DELETE FROM schedule_periods WHERE payment_id = ?", (payment_id,))
    conn.execute("DELETE FROM recurring_payments WHERE id = ?", (payment_id,))


def _payment_from_row(conn: sqlite3.Connection, row: tuple) -> RecurringPayment:
    (
        payment_id,
        detection_key,
        name,
        category,
        status,
        source,
        name_locked,
        schedule_locked,
        last_paid_date,
    ) = row
    return RecurringPayment(
        id=payment_id,
        detection_key=detection_key,
        name=name,
        category=category,
        status=status,
        source=source,
        name_locked=bool(name_locked),
        schedule_locked=bool(schedule_locked),
        last_paid_date=date.fromisoformat(last_paid_date) if last_paid_date else None,
        periods=_load_periods(conn, payment_id),
    )


def _load_periods(conn: sqlite3.Connection, payment_id: int) -> tuple[SchedulePeriod, ...]:
    rows = conn.execute(
        "SELECT starts_on, until, amount_cents, interval_months, day "
        "FROM schedule_periods WHERE payment_id = ? ORDER BY starts_on",
        (payment_id,),
    ).fetchall()
    return tuple(
        SchedulePeriod(
            starts_on=date.fromisoformat(starts_on),
            until=date.fromisoformat(until) if until else None,
            amount_cents=amount_cents,
            interval_months=interval_months,
            day=day,
        )
        for starts_on, until, amount_cents, interval_months, day in rows
    )


def _insert_periods(
    conn: sqlite3.Connection, payment_id: int, periods: tuple[SchedulePeriod, ...]
) -> None:
    conn.executemany(
        """
        INSERT INTO schedule_periods (
            payment_id, starts_on, until, amount_cents, interval_months, day
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                payment_id,
                p.starts_on.isoformat(),
                p.until.isoformat() if p.until else None,
                p.amount_cents,
                p.interval_months,
                p.day,
            )
            for p in periods
        ],
    )


def _replace_periods(
    conn: sqlite3.Connection, payment_id: int, periods: tuple[SchedulePeriod, ...]
) -> None:
    # Foreign keys are off in db.connect, so old periods must be deleted explicitly.
    conn.execute("DELETE FROM schedule_periods WHERE payment_id = ?", (payment_id,))
    _insert_periods(conn, payment_id, periods)


def _latest_period(periods: tuple[SchedulePeriod, ...]) -> SchedulePeriod:
    return max(periods, key=lambda p: p.starts_on)
