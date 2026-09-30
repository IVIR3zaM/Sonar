"""The import page."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.categorization.rules import Rule
from sonar.categorization.store import load_stored_taxonomy
from sonar.db import connect
from sonar.importing.importers import UnknownFormatError
from sonar.importing.store import import_file
from sonar.recurring.store import sync_detected


def _import_one(
    conn: sqlite3.Connection, content: bytes, filename: str, rules: tuple[Rule, ...]
) -> dict:
    """Import one file, turning an unrecognized format into a display-ready row."""
    try:
        result = import_file(conn, content, filename, rules=rules)
    except UnknownFormatError as error:
        return {"filename": filename, "error": str(error)}
    return {
        "filename": result.filename,
        "format": result.format,
        "added": result.added,
        "duplicates": result.duplicates,
        "uncategorized": result.uncategorized,
    }


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/import", response_class=HTMLResponse)
    async def import_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "import.html")

    @router.post("/import", response_class=HTMLResponse)
    async def import_upload(
        request: Request,
        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI's required pattern
    ) -> HTMLResponse:
        # One connection for the whole upload; one file's failure (unknown
        # format) must not stop the others in the same request. The taxonomy
        # is loaded once per request, not once per file, so all files in one
        # upload see the same rule set.
        conn = connect(db_path)
        try:
            taxonomy = load_stored_taxonomy(conn)
            results = [
                _import_one(conn, await f.read(), f.filename or "", taxonomy.rules) for f in files
            ]
            # Once per request, after every file, so detection sees the full upload.
            sync_detected(conn, taxonomy.categories, today())
        finally:
            conn.close()
        return templates.TemplateResponse(request, "import_results.html", {"results": results})

    return router
