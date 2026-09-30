"""The Keep-the-lights-on page."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from fractions import Fraction
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.cashflow import lights_on
from sonar.cashflow.monthly import Period
from sonar.cashflow.store import current_balance, load_settings
from sonar.categorization.groups import LIGHTS_ON
from sonar.categorization.store import load_stored_taxonomy, transactions_with_category
from sonar.db import connect
from sonar.web import charts


def _cents(amount: Fraction) -> int:
    # Half a cent rounds up, like lights_on.py's own rounding; these Fraction
    # amounts are never negative.
    return math.floor(amount + Fraction(1, 2))


def _lights_on_table_rows(
    months: list[lights_on.MonthSpend], categories: list[str], used: tuple[Period, ...]
) -> list[dict]:
    """One row per month, in cents, for the Keep-the-lights-on table."""
    return [
        {
            "period": m.period,
            "used": m.period in used,
            "total_cents": _cents(m.daily_lights_on),
            "by_category": {c: _cents(m.daily_by_category.get(c, Fraction(0))) for c in categories},
            "occasional_cents": _cents(m.daily_occasional),
        }
        for m in months
    ]


def _lights_on_chart_series(
    months: list[lights_on.MonthSpend], categories: list[str]
) -> list[dict]:
    """Total (if any category is set up) + one line per category + Occasional."""
    series = []
    if categories:
        series.append(
            {"name": "Keep the lights on", "values": [_cents(m.daily_lights_on) for m in months]}
        )
    series.extend(
        {
            "name": category,
            "values": [_cents(m.daily_by_category.get(category, Fraction(0))) for m in months],
        }
        for category in categories
    )
    series.append(
        {
            "name": "Occasional payments (not forecast)",
            "values": [_cents(m.daily_occasional) for m in months],
            "muted": True,
        }
    )
    return series


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/lights-on", response_class=HTMLResponse)
    async def lights_on_page(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            taxonomy = load_stored_taxonomy(conn)
            rows = transactions_with_category(conn)
            salary_day = load_settings(conn).salary_day
            balance = current_balance(conn)
        finally:
            conn.close()
        categories = sorted(
            name for name, group in taxonomy.categories.items() if group == LIGHTS_ON
        )
        until = lights_on.last_known_day(rows, balance.as_of if balance else None)
        months = (
            []
            if until is None
            else lights_on.month_spends(rows, taxonomy.categories, salary_day, until)
        )
        shown = months[-24:]
        recent = lights_on.lights_on_forecast(months, 1)
        return templates.TemplateResponse(
            request,
            "lights_on.html",
            {
                "categories": categories,
                "months": shown,
                "chart_labels": [charts.month_label(m.period.month) for m in shown],
                "daily": recent,
                "salary_months": salary_day is not None,
                "table_rows": _lights_on_table_rows(
                    shown, categories, recent.months_used if recent else ()
                ),
                "chart_series": _lights_on_chart_series(shown, categories),
            },
        )

    return router
