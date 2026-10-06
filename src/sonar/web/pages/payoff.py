"""The payoff page: what fixed costs each cumulative debt payoff frees."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.cashflow.service import load_payoff
from sonar.db import connect
from sonar.web import charts


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/payoff", response_class=HTMLResponse)
    async def payoff(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            ladder = load_payoff(conn, today())
        finally:
            conn.close()
        ticks = charts.payoff_ticks([step.pay_now_cents for step in ladder.steps])
        return templates.TemplateResponse(
            request, "payoff.html", {"payoff": ladder, "ticks": ticks}
        )

    return router
