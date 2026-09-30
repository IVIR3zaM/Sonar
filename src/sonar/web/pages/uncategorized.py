"""The uncategorized page, its reapply action and the nav badge."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.categorization.export import build_categorization_request
from sonar.categorization.service import reapply_stored_taxonomy
from sonar.categorization.store import uncategorized_count, uncategorized_transactions
from sonar.db import connect


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _nav_badge(count: int, oob: bool = False) -> str:
        macro = templates.get_template("components/nav_badge.html").module.nav_badge
        return str(macro(count, oob))

    @router.get("/uncategorized", response_class=HTMLResponse)
    async def uncategorized_page(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            txs = uncategorized_transactions(conn)
        finally:
            conn.close()
        return templates.TemplateResponse(
            request,
            "uncategorized.html",
            {
                "transactions": txs,
                "count": len(txs),
                "request_text": build_categorization_request(txs),
            },
        )

    @router.post("/reapply", response_class=HTMLResponse)
    async def reapply(request: Request) -> HTMLResponse:
        # Reloads the taxonomy stored in the DB so an edit made through the
        # Categories page or the API takes effect without restarting the app.
        conn = connect(db_path)
        try:
            count = reapply_stored_taxonomy(conn, today())
        finally:
            conn.close()
        # The nav badge rides along out of band so it agrees with the page count.
        return HTMLResponse(
            f'<span id="uncategorized-count">{count}</span>{_nav_badge(count, oob=True)}'
        )

    @router.get("/uncategorized/badge", response_class=HTMLResponse)
    async def uncategorized_badge() -> HTMLResponse:
        conn = connect(db_path)
        try:
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return HTMLResponse(_nav_badge(count))

    return router
