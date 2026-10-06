"""The Keep-the-lights-on page."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.cashflow import lights_on
from sonar.cashflow.service import load_lights_on
from sonar.categorization.store import load_stored_taxonomy
from sonar.db import connect
from sonar.web import charts


def _lights_on_chart_series(
    rows: Sequence[lights_on.MonthRow], categories: Sequence[str]
) -> list[dict]:
    """Total (if any category is set up) + one line per category + Occasional."""
    series = []
    if categories:
        series.append({"name": "Keep the lights on", "values": [r.total_cents for r in rows]})
    series.extend(
        {"name": category, "values": [r.by_category[category] for r in rows]}
        for category in categories
    )
    series.append(
        {
            "name": "Occasional payments (not forecast)",
            "values": [r.occasional_cents for r in rows],
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
            view = load_lights_on(conn, load_stored_taxonomy(conn).categories)
        finally:
            conn.close()
        rows = lights_on.month_rows(
            view.months, view.categories, view.daily.months_used if view.daily else ()
        )
        return templates.TemplateResponse(
            request,
            "lights_on.html",
            {
                "categories": view.categories,
                "months": view.months,
                "chart_labels": [charts.month_label(m.period.month) for m in view.months],
                "daily": view.daily,
                "salary_months": view.salary_months,
                "table_rows": rows,
                "chart_series": _lights_on_chart_series(rows, view.categories),
            },
        )

    return router
