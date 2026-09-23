"""FastAPI application factory."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.db import apply_migrations, connect
from sonar.importers import UnknownFormatError
from sonar.importing import import_file

# Resolved relative to this module, not the process CWD, so migrations are
# found regardless of where the app is launched from.
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def create_app(db_path: Path = Path("data/sonar.db")) -> FastAPI:
    """Build the Sonar FastAPI app, migrating `db_path` on startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = connect(db_path)
        try:
            apply_migrations(conn, MIGRATIONS_DIR)
        finally:
            conn.close()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html")

    @app.get("/import", response_class=HTMLResponse)
    async def import_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "import.html")

    @app.post("/import", response_class=HTMLResponse)
    async def import_upload(
        request: Request,
        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI's required pattern
    ) -> HTMLResponse:
        # One connection for the whole upload; one file's failure (unknown
        # format) must not stop the others in the same request.
        conn = connect(db_path)
        try:
            results = [_import_one(conn, await f.read(), f.filename or "") for f in files]
        finally:
            conn.close()
        return templates.TemplateResponse(request, "import_results.html", {"results": results})

    return app


def _import_one(conn: sqlite3.Connection, content: bytes, filename: str) -> dict:
    """Import one file, turning an unrecognized format into a display-ready row."""
    try:
        result = import_file(conn, content, filename)
    except UnknownFormatError as error:
        return {"filename": filename, "error": str(error)}
    return {
        "filename": result.filename,
        "format": result.format,
        "added": result.added,
        "duplicates": result.duplicates,
        "uncategorized": result.uncategorized,
    }
