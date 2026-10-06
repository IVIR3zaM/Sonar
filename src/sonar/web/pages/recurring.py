"""The recurring payments page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.db import connect
from sonar.debts.store import debt_overview
from sonar.money import parse_cents
from sonar.recurring.schedule import SchedulePeriod, next_due_date
from sonar.recurring.store import (
    add_manual,
    dismiss,
    edit_payment,
    list_payments,
    pause_payment,
    resume_payment,
)
from sonar.web import forms


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _render_recurring_page(
        request: Request, status_code: int = 200, errors: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and every /recurring POST error path, so a
        # 400 re-render always shows the same page a fresh GET would.
        errors = errors or {}
        conn = connect(db_path)
        try:
            payments = list_payments(conn)
            # Inverted from debt_overview's debt -> payments so the payment row
            # can show which debt (if any) it is already counted as (SPEC §7).
            debt_names_by_payment_id = {
                payment.id: view.debt.name
                for view in debt_overview(conn, today())
                for payment in view.linked_payments
            }
            # periods come back ordered by starts_on, so [-1] is the latest.
            rows = [
                {
                    "payment": payment,
                    "latest": payment.periods[-1],
                    "next_due": next_due_date(payment.periods, payment.last_paid_date, today()),
                    "debt_name": debt_names_by_payment_id.get(payment.id),
                    "edit_error": forms.row_error(errors, "edit", payment.id),
                    "pause_error": forms.row_error(errors, "pause", payment.id),
                    "resume_error": forms.row_error(errors, "resume", payment.id),
                }
                for payment in payments
            ]
        finally:
            conn.close()
        return templates.TemplateResponse(
            request,
            "recurring.html",
            {"rows": rows, "add_error": errors.get("add")},
            status_code=status_code,
        )

    @router.get("/recurring", response_class=HTMLResponse)
    async def recurring_page(request: Request) -> HTMLResponse:
        return _render_recurring_page(request)

    @router.post("/recurring")
    async def add_recurring(
        request: Request,
        name: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(...),
        starts_on: str = Form(...),
        description: str = Form(""),
    ) -> HTMLResponse:
        try:
            period = SchedulePeriod(
                starts_on=forms.field("First due date", starts_on, "date", date.fromisoformat),
                until=None,
                amount_cents=forms.field("Amount", amount, "amount", parse_cents),
                interval_months=forms.field("Every (months)", interval_months, "int", int),
                day=forms.field("Day", day, "int", int),
            )
        except ValueError as error:
            values = {
                "name": name,
                "amount": amount,
                "interval_months": interval_months,
                "day": day,
                "starts_on": starts_on,
                "description": description,
            }
            return _render_recurring_page(
                request,
                status_code=400,
                errors={"add": {"message": forms.friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            add_manual(conn, name, None, period, description)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @router.post("/recurring/{id}/edit")
    async def edit_recurring(
        request: Request,
        id: int,
        name: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(...),
        description: str = Form(""),
    ) -> HTMLResponse:
        try:
            amount_cents = forms.field("Amount", amount, "amount", parse_cents)
            interval = forms.field("Every (months)", interval_months, "int", int)
            day_number = forms.field("Day", day, "int", int)
            _validate_schedule(amount_cents, interval, day_number)
        except ValueError as error:
            values = {
                "name": name,
                "amount": amount,
                "interval_months": interval_months,
                "day": day,
                "description": description,
            }
            return _render_recurring_page(
                request,
                status_code=400,
                errors={"edit": {"id": id, "message": forms.friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            edit_payment(conn, id, name, amount_cents, interval, day_number, description)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @router.post("/recurring/{id}/dismiss")
    async def dismiss_recurring(id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            dismiss(conn, id)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @router.post("/recurring/{id}/pause")
    async def pause_recurring(
        request: Request, id: int, last_date: str = Form(...)
    ) -> HTMLResponse:
        try:
            parsed_last_date = forms.field(
                "Ends/pauses after", last_date, "date", date.fromisoformat
            )
        except ValueError as error:
            return _render_recurring_page(
                request,
                status_code=400,
                errors={
                    "pause": {
                        "id": id,
                        "message": forms.friendly(error),
                        "fields": {"last_date": last_date},
                    }
                },
            )
        conn = connect(db_path)
        try:
            pause_payment(conn, id, parsed_last_date)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @router.post("/recurring/{id}/resume")
    async def resume_recurring(
        request: Request,
        id: int,
        starts_on: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(""),
    ) -> HTMLResponse:
        try:
            parsed_starts_on = forms.field("Resumes on", starts_on, "date", date.fromisoformat)
            amount_cents = forms.field("Amount", amount, "amount", parse_cents)
            interval = forms.field("Every (months)", interval_months, "int", int)
            # Day defaults to the resume date's own day, same as schedule.resume_on.
            day_number = forms.field("Day", day, "int", int) if day else parsed_starts_on.day
            _validate_schedule(amount_cents, interval, day_number)
        except ValueError as error:
            values = {
                "starts_on": starts_on,
                "amount": amount,
                "interval_months": interval_months,
                "day": day,
            }
            return _render_recurring_page(
                request,
                status_code=400,
                errors={"resume": {"id": id, "message": forms.friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            resume_payment(conn, id, parsed_starts_on, amount_cents, interval, day_number)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    return router


def _validate_schedule(amount_cents: int, interval_months: int, day: int) -> None:
    # Reuses SchedulePeriod's own checks instead of duplicating them; the
    # starts_on value here is a placeholder, only used to satisfy the dataclass.
    SchedulePeriod(
        starts_on=date(2000, 1, 1),
        until=None,
        amount_cents=amount_cents,
        interval_months=interval_months,
        day=day,
    )
