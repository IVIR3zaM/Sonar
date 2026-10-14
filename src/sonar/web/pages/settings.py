"""The settings page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.banking.consent import card_status
from sonar.banking.store import load_connection
from sonar.cashflow.store import current_balance, load_settings, save_settings, set_manual_balance
from sonar.db import connect
from sonar.money import parse_signed_cents
from sonar.web import forms


def render_settings_page(
    request: Request,
    db_path: Path,
    today: Callable[[], date],
    templates: Jinja2Templates,
    status_code: int = 200,
    error: dict | None = None,
) -> HTMLResponse:
    """The settings page; shared by the GET route, the POST error paths and the bank flow.

    The bank card only exists when bank sync is on (`app.state.bank_enabled`).
    """
    bank_enabled = request.app.state.bank_enabled
    day = today()
    conn = connect(db_path)
    try:
        settings = load_settings(conn)
        balance = current_balance(conn)
        connection = load_connection(conn) if bank_enabled else None
    finally:
        conn.close()
    context = {
        "settings": settings,
        "balance": balance,
        "today": day,
        "error": error,
        "bank_enabled": bank_enabled,
    }
    if bank_enabled:
        context |= {"connection": connection, "card_status": card_status(connection, day)}
    return templates.TemplateResponse(request, "settings.html", context, status_code=status_code)


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        return render_settings_page(request, db_path, today, templates)

    @router.post("/settings")
    async def update_settings(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        salary_day: str = Form(""),
        overdraft_limit: str = Form(""),
    ) -> HTMLResponse:
        values = {"salary_day": salary_day, "overdraft_limit": overdraft_limit}
        try:
            salary_day_number = forms.field("Salary day", salary_day, "int", int)
            overdraft_limit_cents = forms.field(
                "Overdraft limit", overdraft_limit, "amount", parse_signed_cents
            )
        except ValueError as error:
            return render_settings_page(
                request,
                db_path,
                today,
                templates,
                status_code=400,
                error={"form": "settings", "message": forms.friendly(error), "fields": values},
            )
        conn = connect(db_path)
        try:
            save_settings(conn, salary_day_number, overdraft_limit_cents)
        except ValueError as error:
            return render_settings_page(
                request,
                db_path,
                today,
                templates,
                status_code=400,
                error={"form": "settings", "message": forms.friendly(error), "fields": values},
            )
        finally:
            conn.close()
        return RedirectResponse("/settings", status_code=303)

    @router.post("/settings/balance")
    async def update_balance(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        amount: str = Form(""),
        as_of: str = Form(""),
    ) -> HTMLResponse:
        values = {"amount": amount, "as_of": as_of}
        try:
            amount_cents = forms.field("Amount", amount, "amount", parse_signed_cents)
            as_of_date = forms.field("As of", as_of, "date", date.fromisoformat)
        except ValueError as error:
            return render_settings_page(
                request,
                db_path,
                today,
                templates,
                status_code=400,
                error={"form": "balance", "message": forms.friendly(error), "fields": values},
            )
        conn = connect(db_path)
        try:
            set_manual_balance(conn, as_of_date, amount_cents, today())
        except ValueError as error:
            return render_settings_page(
                request,
                db_path,
                today,
                templates,
                status_code=400,
                error={"form": "balance", "message": forms.friendly(error), "fields": values},
            )
        finally:
            conn.close()
        return RedirectResponse("/settings", status_code=303)

    return router
