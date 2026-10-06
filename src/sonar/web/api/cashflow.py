"""Dashboard and Keep-the-lights-on endpoints (SPEC §9, §13 Pages): the pages' figures as JSON.

Both read through `cashflow.service`, the same loading the pages use, so a
forecast rule lives in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter

from sonar.cashflow.lights_on import month_rows
from sonar.cashflow.service import load_dashboard, load_lights_on
from sonar.categorization.store import load_stored_taxonomy
from sonar.db import connect
from sonar.web.api._common import _jsonable


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

    @router.get("/dashboard")
    async def get_dashboard() -> dict:
        conn = connect(db_path)
        try:
            board = load_dashboard(conn, load_stored_taxonomy(conn).categories, today())
        finally:
            conn.close()
        body = _jsonable(board)
        body["debts"] = [{"name": name, "remaining_cents": cents} for name, cents in board.debts]
        return body

    @router.get("/lights-on")
    async def get_lights_on() -> dict:
        conn = connect(db_path)
        try:
            view = load_lights_on(conn, load_stored_taxonomy(conn).categories)
        finally:
            conn.close()
        used = view.daily.months_used if view.daily else ()
        return {
            "categories": list(view.categories),
            "salary_months": view.salary_months,
            "daily": _jsonable(view.daily),
            "months": _jsonable(month_rows(view.months, view.categories, used)),
        }

    return router
