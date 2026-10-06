"""The monthly spending page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from sonar.cashflow.monthly import UNCATEGORIZED, only_category, parse_month
from sonar.cashflow.service import load_monthly
from sonar.categorization.store import load_stored_taxonomy
from sonar.db import connect


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/monthly", response_class=HTMLResponse)
    async def monthly_page(
        request: Request, month: str | None = None, category: str | None = None
    ) -> HTMLResponse:
        try:
            selected = None if month is None else parse_month(month)
        except ValueError:
            raise StarletteHTTPException(status_code=404) from None
        conn = connect(db_path)
        try:
            view = load_monthly(conn, load_stored_taxonomy(conn).categories, today(), selected)
        finally:
            conn.close()
        spending = view.spending
        # The category table always shows the whole month; only the payment
        # list below it narrows to the chosen category.
        category = category or None
        return templates.TemplateResponse(
            request,
            "monthly.html",
            {
                "spending": spending,
                "category": category,
                "category_label": "Uncategorized" if category == UNCATEGORIZED else category,
                "payments": (
                    only_category(spending.payments, category) if category else spending.payments
                ),
                "salary_months": view.salary_months,
                "months": view.months,
                "older": view.older,
                "newer": view.newer,
            },
        )

    return router
