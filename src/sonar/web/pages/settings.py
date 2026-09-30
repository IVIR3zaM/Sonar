"""The settings page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.cashflow.store import current_balance, load_settings, save_settings, set_manual_balance
from sonar.db import connect
from sonar.money import parse_signed_cents
from sonar.web import forms


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _render_settings_page(
        request: Request, status_code: int = 200, error: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and both settings POST error paths.
        conn = connect(db_path)
        try:
            settings = load_settings(conn)
            balance = current_balance(conn)
        finally:
            conn.close()
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"settings": settings, "balance": balance, "today": today(), "error": error},
            status_code=status_code,
        )

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        return _render_settings_page(request)

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
            return _render_settings_page(
                request,
                status_code=400,
                error={"form": "settings", "message": forms.friendly(error), "fields": values},
            )
        conn = connect(db_path)
        try:
            save_settings(conn, salary_day_number, overdraft_limit_cents)
        except ValueError as error:
            return _render_settings_page(
                request,
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
            return _render_settings_page(
                request,
                status_code=400,
                error={"form": "balance", "message": forms.friendly(error), "fields": values},
            )
        conn = connect(db_path)
        try:
            set_manual_balance(conn, as_of_date, amount_cents, today())
        except ValueError as error:
            return _render_settings_page(
                request,
                status_code=400,
                error={"form": "balance", "message": forms.friendly(error), "fields": values},
            )
        finally:
            conn.close()
        return RedirectResponse("/settings", status_code=303)

    return router
