"""The debts page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.db import connect
from sonar.debts.model import Installment, Loan, MatchRule
from sonar.debts.store import add_debt, debt_overview, delete_debt, remaining_cents
from sonar.money import parse_basis_points, parse_cents
from sonar.web import forms


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _render_debts_page(
        request: Request, status_code: int = 200, errors: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and the two add-debt POST error paths.
        errors = errors or {}
        conn = connect(db_path)
        try:
            views = debt_overview(conn, today())
        finally:
            conn.close()
        installments = [v for v in views if isinstance(v.debt, Installment)]
        loans = [v for v in views if isinstance(v.debt, Loan)]
        # Shares the "one remaining figure per debt kind" rule with the
        # dashboard (SPEC §9 section 3) instead of re-deriving it here.
        total_remaining = sum(remaining_cents(v) for v in views)
        return templates.TemplateResponse(
            request,
            "debts.html",
            {
                "installments": installments,
                "loans": loans,
                "total_remaining": total_remaining,
                "installment_error": errors.get("installment"),
                "loan_error": errors.get("loan"),
            },
            status_code=status_code,
        )

    @router.get("/debts", response_class=HTMLResponse)
    async def debts_page(request: Request) -> HTMLResponse:
        return _render_debts_page(request)

    @router.post("/debts/installments")
    async def add_installment(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        name: str = Form(""),
        total: str = Form(""),
        rate: str = Form(""),
        interval_months: str = Form(""),
        first_payment_date: str = Form(""),
        payments_count: str = Form(""),
        match_field: str = Form(""),
        match_value: str = Form(""),
    ) -> HTMLResponse:
        try:
            debt = Installment(
                name=name,
                total_cents=forms.field("Total", total, "amount", parse_cents),
                rate_cents=forms.field("Rate", rate, "amount", parse_cents),
                interval_months=forms.field("Every N month(s)", interval_months, "int", int),
                first_payment_date=forms.field(
                    "First payment", first_payment_date, "date", date.fromisoformat
                ),
                payments_count=forms.field("Number of payments", payments_count, "int", int),
                match=MatchRule(match_field, match_value),
            )
        except ValueError as error:
            values = {
                "name": name,
                "total": total,
                "rate": rate,
                "interval_months": interval_months,
                "first_payment_date": first_payment_date,
                "payments_count": payments_count,
                "match_field": match_field,
                "match_value": match_value,
            }
            return _render_debts_page(
                request,
                status_code=400,
                errors={"installment": {"message": forms.friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            add_debt(conn, debt)
        finally:
            conn.close()
        return RedirectResponse("/debts", status_code=303)

    @router.post("/debts/loans")
    async def add_loan(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        name: str = Form(""),
        balance: str = Form(""),
        balance_as_of: str = Form(""),
        rate: str = Form(""),
        interest: str = Form(""),
        match_field: str = Form(""),
        match_value: str = Form(""),
    ) -> HTMLResponse:
        try:
            debt = Loan(
                name=name,
                balance_cents=forms.field("Balance", balance, "amount", parse_cents),
                balance_as_of=forms.field("As of", balance_as_of, "date", date.fromisoformat),
                rate_cents=forms.field("Monthly rate", rate, "amount", parse_cents),
                # An empty field means no interest was entered, not a 0% rate,
                # so the loan amortizes linearly (see debts/amortization.loan_schedule).
                interest_bp=(
                    forms.field("Interest", interest, "percent", parse_basis_points)
                    if interest.strip()
                    else None
                ),
                match=MatchRule(match_field, match_value),
            )
        except ValueError as error:
            values = {
                "name": name,
                "balance": balance,
                "balance_as_of": balance_as_of,
                "rate": rate,
                "interest": interest,
                "match_field": match_field,
                "match_value": match_value,
            }
            return _render_debts_page(
                request,
                status_code=400,
                errors={"loan": {"message": forms.friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            add_debt(conn, debt)
        finally:
            conn.close()
        return RedirectResponse("/debts", status_code=303)

    @router.post("/debts/{id}/delete")
    async def delete_debt_route(id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            delete_debt(conn, id)
        finally:
            conn.close()
        return RedirectResponse("/debts", status_code=303)

    return router
