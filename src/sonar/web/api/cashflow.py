"""Dashboard, Keep-the-lights-on, monthly and transactions endpoints (SPEC §9, §13 Pages).

The page figures read through `cashflow.service`, the same loading the pages
use, so a forecast rule lives in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from sonar.cashflow.lights_on import month_rows
from sonar.cashflow.monthly import only_category, parse_month
from sonar.cashflow.service import load_dashboard, load_lights_on, load_monthly
from sonar.categorization.store import load_stored_taxonomy, transactions_with_category
from sonar.db import connect
from sonar.transactions import ParsedTransaction
from sonar.web.api._common import _jsonable


def _bad_request(message: str, field: str) -> JSONResponse:
    return JSONResponse({"error": message, "field": field}, status_code=400)


def _transaction_item(tx: ParsedTransaction, category: str | None) -> dict:
    return {
        "booking_date": tx.booking_date.isoformat(),
        "value_date": tx.value_date.isoformat(),
        "amount_cents": tx.amount_cents,
        "currency": tx.currency,
        "counterparty": tx.counterparty,
        "purpose": tx.purpose,
        "account": tx.account,
        "iban": tx.iban,
        "mandate_ref": tx.mandate_ref,
        "creditor_id": tx.creditor_id,
        "category": category,
    }


def _parse_day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _matches(tx: ParsedTransaction, needle: str) -> bool:
    return needle in tx.counterparty.casefold() or needle in tx.purpose.casefold()


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

    @router.get("/dashboard")
    async def get_dashboard() -> dict:
        conn = connect(db_path)
        try:
            board = load_dashboard(conn, load_stored_taxonomy(conn).categories, today())
        finally:
            conn.close()
        body = _jsonable(board)
        body["debts"] = [{"name": name, "remaining_cents": cents} for name, cents in board.debts]
        return body

    @router.get("/lights-on")
    async def get_lights_on() -> dict:
        conn = connect(db_path)
        try:
            view = load_lights_on(conn, load_stored_taxonomy(conn).categories)
        finally:
            conn.close()
        used = view.daily.months_used if view.daily else ()
        return {
            "categories": list(view.categories),
            "salary_months": view.salary_months,
            "daily": _jsonable(view.daily),
            "months": _jsonable(month_rows(view.months, view.categories, used)),
        }

    @router.get("/monthly")
    async def get_monthly(month: str | None = None, category: str | None = None):
        try:
            selected = None if month is None else parse_month(month)
        except ValueError as error:
            return _bad_request(str(error), "month")
        conn = connect(db_path)
        try:
            view = load_monthly(conn, load_stored_taxonomy(conn).categories, today(), selected)
        finally:
            conn.close()
        spending = view.spending
        payments = only_category(spending.payments, category) if category else spending.payments
        return {
            "month": spending.period.month.isoformat(),
            "start": spending.period.start.isoformat(),
            "end": spending.period.end.isoformat(),
            "salary_months": view.salary_months,
            "months": [m.isoformat() for m in view.months],
            "older": _jsonable(view.older),
            "newer": _jsonable(view.newer),
            "spent_cents": spending.spent_cents,
            "transfers_net_cents": spending.transfers_net_cents,
            "groups": _jsonable(spending.groups),
            "by_category": _jsonable(spending.by_category),
            "transfer_totals": _jsonable(spending.transfer_totals),
            "payments": [_transaction_item(tx, tx_category) for tx, tx_category in payments],
        }

    @router.get("/transactions")
    async def get_transactions(
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
        category: str | None = None,
        uncategorized: str | None = None,
        q: str | None = None,
    ):
        try:
            first = _parse_day(from_)
        except ValueError:
            return _bad_request("from must look like YYYY-MM-DD", "from")
        try:
            last = _parse_day(to)
        except ValueError:
            return _bad_request("to must look like YYYY-MM-DD", "to")
        if uncategorized not in (None, "", "true", "false"):
            return _bad_request("uncategorized must be true or false", "uncategorized")
        only_uncategorized = uncategorized == "true"
        if only_uncategorized and category:
            return _bad_request("category and uncategorized cannot be combined", "uncategorized")
        needle = (q or "").casefold()
        conn = connect(db_path)
        try:
            rows = transactions_with_category(conn)
        finally:
            conn.close()
        kept = [
            (tx, tx_category)
            for tx, tx_category in rows
            if (first is None or tx.booking_date >= first)
            and (last is None or tx.booking_date <= last)
            and (not category or tx_category == category)
            and (not only_uncategorized or tx_category is None)
            and _matches(tx, needle)
        ]
        kept.sort(key=lambda row: row[0].booking_date, reverse=True)
        return {"transactions": [_transaction_item(tx, tx_category) for tx, tx_category in kept]}

    return router
