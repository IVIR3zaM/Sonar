"""The monthly spending page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from sonar.cashflow.monthly import (
    UNCATEGORIZED,
    adjacent_months,
    monthly_spending,
    only_category,
    parse_month,
    payment_months,
    period_for,
    salary_paydays,
)
from sonar.cashflow.store import load_settings
from sonar.categorization.store import load_stored_taxonomy, transactions_with_category
from sonar.db import connect


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/monthly", response_class=HTMLResponse)
    async def monthly_page(
        request: Request, month: str | None = None, category: str | None = None
    ) -> HTMLResponse:
        conn = connect(db_path)
        try:
            taxonomy = load_stored_taxonomy(conn)
            rows = transactions_with_category(conn)
            salary_day = load_settings(conn).salary_day
        finally:
            conn.close()
        paydays = salary_paydays(rows)
        months = payment_months(rows, salary_day, paydays)
        if month is None:
            # The latest month with data rather than the clock's: exports are
            # often weeks old, and an empty current month would open the page.
            selected = months[0] if months else today().replace(day=1)
        else:
            try:
                selected = parse_month(month)
            except ValueError:
                raise StarletteHTTPException(status_code=404) from None
        older, newer = adjacent_months(months, selected)
        spending = monthly_spending(
            rows, taxonomy.categories, period_for(selected, salary_day, paydays)
        )
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
                "salary_months": salary_day is not None,
                "months": months,
                "older": older,
                "newer": newer,
            },
        )

    return router
