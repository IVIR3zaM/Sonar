"""DB shell for installments and loans (SPEC §7): storage only.

`model.py` holds the pure model and status calculations. This module just
persists the hand-entered debt rows so they survive restarts and upgrades,
per SPEC §3's rule that hand-entered data must survive schema changes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.categorization.store import list_categories, transactions_with_category
from sonar.debts.drafts import DraftPrefill, draft_prefill, qualifies
from sonar.debts.model import (
    Installment,
    InstallmentStatus,
    Loan,
    LoanStatus,
    MatchRule,
    installment_status,
    linked_keys,
    loan_status,
)
from sonar.recurring.store import RecurringPayment, list_payments

_COLUMNS = (
    "id, kind, name, rate_cents, match_field, match_value, "
    "total_cents, interval_months, first_payment_date, payments_count, "
    "balance_cents, balance_as_of, interest_bp"
)


class DebtNotFound(LookupError):
    """Raised by delete_debt when `id` has no matching row."""


class DraftNotFound(LookupError):
    """Raised by complete_draft when `id` has no open draft."""


@dataclass(frozen=True)
class StoredDebt:
    id: int
    debt: Installment | Loan


@dataclass(frozen=True)
class DebtView:
    id: int
    debt: Installment | Loan
    status: InstallmentStatus | LoanStatus
    linked_payments: tuple[RecurringPayment, ...]


@dataclass(frozen=True)
class DebtDraft:
    id: int
    detection_key: str
    prefill: DraftPrefill


def debt_overview(conn: sqlite3.Connection, today: date) -> list[DebtView]:
    """One row per stored debt, with its status and any linked recurring payment.

    Status is computed fresh from the stored transactions on every call rather
    than cached, so a re-import or re-detection needs no extra sync step. A
    recurring payment is linked when its detection key is one of the debt's
    matching transactions' keys - the same key detection would have grouped
    those transactions under - which is how SPEC §7 avoids counting the same
    payment twice in the forecast.
    """
    txs = [tx for tx, _category in transactions_with_category(conn)]
    active_payments = list_payments(conn)  # a dismissed payment is never linked
    views = []
    for stored in list_debts(conn):
        keys = linked_keys(stored.debt, txs)
        linked = tuple(p for p in active_payments if p.detection_key in keys)
        status: InstallmentStatus | LoanStatus
        if isinstance(stored.debt, Installment):
            status = installment_status(stored.debt, txs)
        else:
            status = loan_status(stored.debt, txs, today)
        views.append(
            DebtView(id=stored.id, debt=stored.debt, status=status, linked_payments=linked)
        )
    return views


def remaining_cents(view: DebtView) -> int:
    """One "amount remaining" figure for either debt kind (SPEC §9 section 3).

    An installment's remaining balance and a loan's projected balance answer
    the same question in different fields, so /debts and the dashboard share
    this instead of branching on kind themselves.
    """
    if isinstance(view.status, InstallmentStatus):
        return view.status.remaining_cents
    return view.status.projected_balance_cents


def sync_drafts(conn: sqlite3.Connection) -> list[DebtDraft]:
    """Bring the drafts in line with the payments, then return the open ones by name.

    Completed rows are never touched: a payment that became a debt once never
    gets a draft again, even after that debt is deleted (SPEC §13 Draft debts).
    """
    txs = [tx for tx, _category in transactions_with_category(conn)]
    debt_categories = {c.name for c in list_categories(conn) if c.debt}
    debt_keys = frozenset().union(*(linked_keys(s.debt, txs) for s in list_debts(conn)))
    prefills = {
        payment.detection_key: prefill
        for payment in list_payments(conn)
        if qualifies(payment, debt_categories, debt_keys)
        and (prefill := draft_prefill(payment, txs)) is not None
    }
    with conn:
        stored = {key for (key,) in conn.execute("SELECT detection_key FROM debt_drafts")}
        conn.executemany(
            "INSERT INTO debt_drafts (detection_key) VALUES (?)",
            [(key,) for key in sorted(prefills.keys() - stored)],
        )
        conn.executemany(
            "DELETE FROM debt_drafts WHERE detection_key = ? AND status = 'open'",
            [(key,) for key in stored - prefills.keys()],
        )
        rows = conn.execute(
            "SELECT id, detection_key FROM debt_drafts WHERE status = 'open'"
        ).fetchall()
    drafts = [DebtDraft(id, key, prefills[key]) for id, key in rows]
    return sorted(drafts, key=lambda draft: draft.prefill.name)


def complete_draft(conn: sqlite3.Connection, draft_id: int, debt: Installment | Loan) -> int:
    """Turn an open draft into an ordinary debt; both writes commit together."""
    with conn:
        row = conn.execute(
            "SELECT 1 FROM debt_drafts WHERE id = ? AND status = 'open'", (draft_id,)
        ).fetchone()
        if row is None:
            raise DraftNotFound(draft_id)
        debt_id = _insert_debt(conn, debt)
        conn.execute("UPDATE debt_drafts SET status = 'completed' WHERE id = ?", (draft_id,))
    return debt_id


def add_debt(conn: sqlite3.Connection, debt: Installment | Loan) -> int:
    """Insert one debt, writing only the columns its kind uses."""
    with conn:
        return _insert_debt(conn, debt)


def add_debt_closing_drafts(conn: sqlite3.Connection, debt: Installment | Loan) -> int:
    """Insert a debt and complete every draft it links, as completing a draft would.

    Drafts are synced first so a qualifying payment that has no row yet still
    ends up completed, and never comes back after the debt is deleted.
    """
    sync_drafts(conn)
    txs = [tx for tx, _category in transactions_with_category(conn)]
    keys = sorted(linked_keys(debt, txs))
    with conn:
        debt_id = _insert_debt(conn, debt)
        conn.executemany(
            "UPDATE debt_drafts SET status = 'completed' "
            "WHERE status = 'open' AND detection_key = ?",
            [(key,) for key in keys],
        )
    return debt_id


def _insert_debt(conn: sqlite3.Connection, debt: Installment | Loan) -> int:
    # No transaction of its own, so complete_draft can pair it with its update.
    if isinstance(debt, Installment):
        cursor = conn.execute(
            """
            INSERT INTO debts (
                kind, name, rate_cents, match_field, match_value,
                total_cents, interval_months, first_payment_date, payments_count
            ) VALUES ('installment', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                debt.name,
                debt.rate_cents,
                debt.match.field,
                debt.match.value,
                debt.total_cents,
                debt.interval_months,
                debt.first_payment_date.isoformat(),
                debt.payments_count,
            ),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO debts (
                kind, name, rate_cents, match_field, match_value,
                balance_cents, balance_as_of, interest_bp
            ) VALUES ('loan', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                debt.name,
                debt.rate_cents,
                debt.match.field,
                debt.match.value,
                debt.balance_cents,
                debt.balance_as_of.isoformat(),
                debt.interest_bp,
            ),
        )
    return cursor.lastrowid


def list_debts(conn: sqlite3.Connection) -> list[StoredDebt]:
    """Installments first, then loans, each ordered by name (SPEC §7 UI order)."""
    rows = conn.execute(f"SELECT {_COLUMNS} FROM debts").fetchall()
    debts = [_debt_from_row(row) for row in rows]
    return sorted(debts, key=lambda stored: (isinstance(stored.debt, Loan), stored.debt.name))


def update_debt(conn: sqlite3.Connection, id: int, debt: Installment | Loan) -> None:
    """Replace a debt's fields in place, keeping its id; the other kind's columns go NULL."""
    installment = debt if isinstance(debt, Installment) else None
    loan = debt if isinstance(debt, Loan) else None
    with conn:
        row = conn.execute("SELECT 1 FROM debts WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise DebtNotFound(id)
        conn.execute(
            """
            UPDATE debts SET
                kind = ?, name = ?, rate_cents = ?, match_field = ?, match_value = ?,
                total_cents = ?, interval_months = ?, first_payment_date = ?,
                payments_count = ?, balance_cents = ?, balance_as_of = ?, interest_bp = ?
            WHERE id = ?
            """,
            (
                "installment" if installment else "loan",
                debt.name,
                debt.rate_cents,
                debt.match.field,
                debt.match.value,
                installment.total_cents if installment else None,
                installment.interval_months if installment else None,
                installment.first_payment_date.isoformat() if installment else None,
                installment.payments_count if installment else None,
                loan.balance_cents if loan else None,
                loan.balance_as_of.isoformat() if loan else None,
                loan.interest_bp if loan else None,
                id,
            ),
        )


def delete_debt(conn: sqlite3.Connection, id: int) -> None:
    with conn:
        row = conn.execute("SELECT 1 FROM debts WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise DebtNotFound(id)
        conn.execute("DELETE FROM debts WHERE id = ?", (id,))


def _debt_from_row(row: tuple) -> StoredDebt:
    (
        id,
        kind,
        name,
        rate_cents,
        match_field,
        match_value,
        total_cents,
        interval_months,
        first_payment_date,
        payments_count,
        balance_cents,
        balance_as_of,
        interest_bp,
    ) = row
    match = MatchRule(match_field, match_value)
    debt: Installment | Loan
    if kind == "installment":
        debt = Installment(
            name=name,
            total_cents=total_cents,
            rate_cents=rate_cents,
            interval_months=interval_months,
            first_payment_date=date.fromisoformat(first_payment_date),
            payments_count=payments_count,
            match=match,
        )
    else:
        debt = Loan(
            name=name,
            balance_cents=balance_cents,
            balance_as_of=date.fromisoformat(balance_as_of),
            rate_cents=rate_cents,
            interest_bp=interest_bp,
            match=match,
        )
    return StoredDebt(id=id, debt=debt)
