"""Debt endpoints (SPEC §7, §13)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StrictInt, StrictStr

from sonar.db import connect
from sonar.debts.model import Installment, InstallmentStatus, Loan, MatchRule
from sonar.debts.store import (
    DebtNotFound,
    DebtView,
    add_debt_closing_drafts,
    debt_overview,
    delete_debt,
    remaining_cents,
)
from sonar.web.api._common import _parse_body, _StrictModel
from sonar.web.forms import friendly

_INSTALLMENT_ONLY = ("total_cents", "interval_months", "first_payment_date", "payments_count")
_LOAN_ONLY = ("balance_cents", "balance_as_of", "interest_bp")
_INSTALLMENT_REQUIRED = (
    "name",
    "total_cents",
    "rate_cents",
    "interval_months",
    "first_payment_date",
    "payments_count",
    "match_field",
    "match_value",
)
_LOAN_REQUIRED = (
    "name",
    "balance_cents",
    "balance_as_of",
    "rate_cents",
    "match_field",
    "match_value",
)
_DATE_FIELDS = ("first_payment_date", "balance_as_of")
# Which request field a domain error belongs to, found by its message text.
_DOMAIN_ERROR_FIELDS = {
    "name must not be blank": "name",
    "total must be positive": "total_cents",
    "rate must be positive": "rate_cents",
    "interval must be at least 1 month": "interval_months",
    "payments_count must be at least 1": "payments_count",
    "balance must be positive": "balance_cents",
    "interest_bp must be positive when set": "interest_bp",
    "field must be one of": "match_field",
    "value must not be blank": "match_value",
}


class DebtIn(_StrictModel):
    kind: StrictStr | None = None
    name: StrictStr | None = None
    match_field: StrictStr | None = None
    match_value: StrictStr | None = None
    first_payment_date: StrictStr | None = None
    balance_as_of: StrictStr | None = None
    total_cents: StrictInt | None = None
    rate_cents: StrictInt | None = None
    interval_months: StrictInt | None = None
    payments_count: StrictInt | None = None
    balance_cents: StrictInt | None = None
    interest_bp: StrictInt | None = None


def _debt_item(view: DebtView) -> dict:
    debt, status = view.debt, view.status
    item: dict = {
        "id": view.id,
        "kind": "installment" if isinstance(debt, Installment) else "loan",
        "name": debt.name,
        "match_field": debt.match.field,
        "match_value": debt.match.value,
        "rate_cents": debt.rate_cents,
        "total_cents": None,
        "interval_months": None,
        "first_payment_date": None,
        "payments_count": None,
        "balance_cents": None,
        "balance_as_of": None,
        "interest_bp": None,
        "remaining_cents": remaining_cents(view),
        "paid_off": status.paid_off,
        "linked_payment_ids": sorted(p.id for p in view.linked_payments),
    }
    if isinstance(debt, Installment) and isinstance(status, InstallmentStatus):
        item |= {
            "total_cents": debt.total_cents,
            "interval_months": debt.interval_months,
            "first_payment_date": debt.first_payment_date.isoformat(),
            "payments_count": debt.payments_count,
            "paid_cents": status.paid_cents,
            "payments_remaining": status.payments_remaining,
            "end_date": status.end_date.isoformat(),
        }
    elif isinstance(debt, Loan) and not isinstance(status, InstallmentStatus):
        payoff = status.payoff_date
        item |= {
            "balance_cents": debt.balance_cents,
            "balance_as_of": debt.balance_as_of.isoformat(),
            "interest_bp": debt.interest_bp,
            "paid_cents": status.paid_since_statement_cents,
            "payments_remaining": None,
            "end_date": payoff.isoformat() if payoff else None,
        }
    return {key: item[key] for key in _DEBT_ITEM_KEYS}


_DEBT_ITEM_KEYS = (
    "id",
    "kind",
    "name",
    "match_field",
    "match_value",
    "rate_cents",
    "total_cents",
    "interval_months",
    "first_payment_date",
    "payments_count",
    "balance_cents",
    "balance_as_of",
    "interest_bp",
    "paid_cents",
    "remaining_cents",
    "payments_remaining",
    "end_date",
    "paid_off",
    "linked_payment_ids",
)


def _bad_debt(error: str, field: str) -> JSONResponse:
    return JSONResponse({"error": error, "field": field}, status_code=400)


def _build_debt(body: DebtIn) -> Installment | Loan | JSONResponse:
    """The domain debt for `body`, or the 400 naming the first field that is wrong."""
    if body.kind not in ("installment", "loan"):
        return _bad_debt("kind must be installment or loan", "kind")
    installment = body.kind == "installment"
    for key in _LOAN_ONLY if installment else _INSTALLMENT_ONLY:
        if getattr(body, key) is not None:
            return _bad_debt(f"{key} does not belong to an {body.kind}", key)
    for key in _INSTALLMENT_REQUIRED if installment else _LOAN_REQUIRED:
        if getattr(body, key) is None:
            return _bad_debt(f"{key} is required", key)
    dates: dict[str, date] = {}
    for key in _DATE_FIELDS:
        text = getattr(body, key)
        if text is None:
            continue
        try:
            dates[key] = date.fromisoformat(text)
        except ValueError:
            return _bad_debt(f"{key} must be a date like 2026-01-31", key)
    try:
        match = MatchRule(body.match_field, body.match_value)
        if installment:
            return Installment(
                name=body.name,
                total_cents=body.total_cents,
                rate_cents=body.rate_cents,
                interval_months=body.interval_months,
                first_payment_date=dates["first_payment_date"],
                payments_count=body.payments_count,
                match=match,
            )
        return Loan(
            name=body.name,
            balance_cents=body.balance_cents,
            balance_as_of=dates["balance_as_of"],
            rate_cents=body.rate_cents,
            interest_bp=body.interest_bp,
            match=match,
        )
    except ValueError as error:
        field = next((f for needle, f in _DOMAIN_ERROR_FIELDS.items() if needle in str(error)), "")
        return _bad_debt(friendly(error), field)


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

    def _find_debt(conn, debt_id: int) -> DebtView:
        for view in debt_overview(conn, today()):
            if view.id == debt_id:
                return view
        raise DebtNotFound(debt_id)

    @router.get("/debts")
    async def get_debts() -> JSONResponse:
        conn = connect(db_path)
        try:
            items = [_debt_item(view) for view in debt_overview(conn, today())]
        finally:
            conn.close()
        return JSONResponse(items)

    @router.post("/debts", status_code=201)
    async def post_debt(request: Request) -> JSONResponse:
        body = await _parse_body(request, DebtIn)
        if isinstance(body, JSONResponse):
            return body
        debt = _build_debt(body)
        if isinstance(debt, JSONResponse):
            return debt
        conn = connect(db_path)
        try:
            item = _debt_item(_find_debt(conn, add_debt_closing_drafts(conn, debt)))
        finally:
            conn.close()
        return JSONResponse(item, status_code=201)

    @router.delete("/debts/{id}")
    async def delete_debt_route(id: int) -> JSONResponse:
        conn = connect(db_path)
        try:
            try:
                item = _debt_item(_find_debt(conn, id))
            except DebtNotFound:
                return JSONResponse({"error": f"No such debt: {id}"}, status_code=404)
            delete_debt(conn, id)
        finally:
            conn.close()
        return JSONResponse(item)

    return router
