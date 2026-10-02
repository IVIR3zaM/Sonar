"""The debts page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.db import connect
from sonar.debts.model import Installment, Loan, MatchRule
from sonar.debts.store import (
    add_debt,
    complete_draft,
    debt_overview,
    delete_debt,
    remaining_cents,
    sync_drafts,
)
from sonar.money import parse_basis_points, parse_cents
from sonar.web import forms

INSTALLMENT_FIELDS = (
    "name",
    "total",
    "rate",
    "interval_months",
    "first_payment_date",
    "payments_count",
    "match_field",
    "match_value",
)
LOAN_FIELDS = (
    "name",
    "balance",
    "balance_as_of",
    "rate",
    "interest",
    "match_field",
    "match_value",
)


async def _form_values(request: Request, names: tuple[str, ...]) -> dict[str, str]:
    # A missing field becomes "" so it reaches our own ValueError -> 400, not FastAPI's 422.
    form = await request.form()
    return {name: str(form.get(name, "")) for name in names}


def _installment_from(values: dict[str, str]) -> Installment:
    """Shared by the add and the complete-draft routes; raises ValueError on a bad field."""
    return Installment(
        name=values["name"],
        total_cents=forms.field("Total", values["total"], "amount", parse_cents),
        rate_cents=forms.field("Rate", values["rate"], "amount", parse_cents),
        interval_months=forms.field("Every N month(s)", values["interval_months"], "int", int),
        first_payment_date=forms.field(
            "First payment", values["first_payment_date"], "date", date.fromisoformat
        ),
        payments_count=forms.field("Number of payments", values["payments_count"], "int", int),
        match=MatchRule(values["match_field"], values["match_value"]),
    )


def _loan_from(values: dict[str, str]) -> Loan:
    """Shared by the add and the complete-draft routes; raises ValueError on a bad field."""
    interest = values["interest"]
    return Loan(
        name=values["name"],
        balance_cents=forms.field("Balance", values["balance"], "amount", parse_cents),
        balance_as_of=forms.field("As of", values["balance_as_of"], "date", date.fromisoformat),
        rate_cents=forms.field("Monthly rate", values["rate"], "amount", parse_cents),
        # An empty field means no interest was entered, not a 0% rate,
        # so the loan amortizes linearly (see debts/amortization.loan_schedule).
        interest_bp=(
            forms.field("Interest", interest, "percent", parse_basis_points)
            if interest.strip()
            else None
        ),
        match=MatchRule(values["match_field"], values["match_value"]),
    )


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _render_debts_page(
        request: Request, status_code: int = 200, errors: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and the POST error paths.
        errors = errors or {}
        conn = connect(db_path)
        try:
            views = debt_overview(conn, today())
            drafts = sync_drafts(conn)
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
                "drafts": drafts,
                "draft_error": errors.get("draft"),
            },
            status_code=status_code,
        )

    @router.get("/debts", response_class=HTMLResponse)
    async def debts_page(request: Request) -> HTMLResponse:
        return _render_debts_page(request)

    @router.post("/debts/installments")
    async def add_installment(request: Request) -> HTMLResponse:
        values = await _form_values(request, INSTALLMENT_FIELDS)
        try:
            debt = _installment_from(values)
        except ValueError as error:
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
    async def add_loan(request: Request) -> HTMLResponse:
        values = await _form_values(request, LOAN_FIELDS)
        try:
            debt = _loan_from(values)
        except ValueError as error:
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

    @router.post("/debts/drafts/{id}/installment")
    async def complete_draft_as_installment(request: Request, id: int) -> HTMLResponse:
        return await _complete_draft(
            request, id, "installment", INSTALLMENT_FIELDS, _installment_from
        )

    @router.post("/debts/drafts/{id}/loan")
    async def complete_draft_as_loan(request: Request, id: int) -> HTMLResponse:
        return await _complete_draft(request, id, "loan", LOAN_FIELDS, _loan_from)

    async def _complete_draft(
        request: Request,
        draft_id: int,
        kind: str,
        field_names: tuple[str, ...],
        build: Callable[[dict[str, str]], Installment | Loan],
    ) -> HTMLResponse:
        values = await _form_values(request, field_names)
        try:
            debt = build(values)
        except ValueError as error:
            draft = {
                "id": draft_id,
                "kind": kind,
                "message": forms.friendly(error),
                "fields": values,
            }
            return _render_debts_page(request, status_code=400, errors={"draft": draft})
        conn = connect(db_path)
        try:
            complete_draft(conn, draft_id, debt)
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
