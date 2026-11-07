"""The monthly spending page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from sonar.cashflow.monthly import UNCATEGORIZED, only_category, only_group, parse_month
from sonar.cashflow.service import load_monthly
from sonar.categorization.groups import LABELS, SPENDING_GROUPS, TRANSFER
from sonar.categorization.store import load_stored_taxonomy
from sonar.db import connect


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/monthly", response_class=HTMLResponse)
    async def monthly_page(
        request: Request,
        month: str | None = None,
        category: str | None = None,
        group: str | None = None,
    ) -> HTMLResponse:
        try:
            selected = None if month is None else parse_month(month)
        except ValueError:
            raise StarletteHTTPException(status_code=404) from None
        if group is not None and group not in (*SPENDING_GROUPS, TRANSFER):
            raise StarletteHTTPException(status_code=404)
        conn = connect(db_path)
        try:
            category_types = load_stored_taxonomy(conn).categories
            view = load_monthly(conn, category_types, today(), selected)
        finally:
            conn.close()
        spending = view.spending
        # The category table always shows the whole month; only the payment
        # list below it narrows to the chosen category.
        category = category or None
        group = None if category else group
        payments = spending.payments
        if category:
            payments = only_category(payments, category)
        elif group:
            payments = only_group(payments, category_types, group)
        return templates.TemplateResponse(
            request,
            "monthly.html",
            {
                "spending": spending,
                "ledger": view.ledger,
                "category": category,
                "category_label": "Uncategorized" if category == UNCATEGORIZED else category,
                "payments": payments,
                "group": group,
                "group_label": LABELS.get(group),
                "group_total_cents": sum(tx.amount_cents for tx, _ in payments),
                "salary_months": view.salary_months,
                "months": view.months,
                "older": view.older,
                "newer": view.newer,
            },
        )

    return router
