"""The dashboard page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.cashflow.service import load_dashboard
from sonar.categorization.store import load_stored_taxonomy
from sonar.db import connect


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            taxonomy = load_stored_taxonomy(conn)
            board = load_dashboard(conn, taxonomy.categories, today())
        finally:
            conn.close()
        return templates.TemplateResponse(request, "index.html", {"dashboard": board})

    return router
