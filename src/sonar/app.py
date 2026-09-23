"""FastAPI application factory."""

from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.categorize import Rule, load_taxonomy
from sonar.categorizing import reapply_rules, uncategorized_count, uncategorized_transactions
from sonar.db import apply_migrations, connect
from sonar.importers import UnknownFormatError
from sonar.importing import import_file
from sonar.uncategorized_export import build_categorization_request

# Resolved relative to this module, not the process CWD, so migrations are
# found regardless of where the app is launched from.
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
TEMPLATES_DIR = Path(__file__).parent / "templates"
CATEGORIES_PATH = Path(__file__).parent / "categories.toml"

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _format_cents(cents: int) -> str:
    # Display-only conversion from integer cents; storage/comparisons never use float.
    sign = "-" if cents < 0 else ""
    whole, remainder = divmod(abs(cents), 100)
    return f"{sign}{whole}.{remainder:02d}"


templates.env.filters["money"] = _format_cents


def create_app(
    db_path: Path = Path("data/sonar.db"),
    categories_path: Path = CATEGORIES_PATH,
) -> FastAPI:
    """Build the Sonar FastAPI app, migrating `db_path` on startup.

    `categories_path` is read fresh on every import and again at startup, so
    editing `categories.toml` by hand (the Categorization workflow) takes
    effect without restarting the app.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = connect(db_path)
        try:
            apply_migrations(conn, MIGRATIONS_DIR)
            reapply_rules(conn, load_taxonomy(categories_path).rules)
        finally:
            conn.close()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return templates.TemplateResponse(request, "index.html", {"uncategorized_count": count})

    @app.get("/uncategorized", response_class=HTMLResponse)
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

    @app.post("/reapply", response_class=HTMLResponse)
    async def reapply(request: Request) -> HTMLResponse:
        # Reloads the taxonomy from disk so a hand edit to categories.toml
        # takes effect without restarting the app (same as a fresh import).
        rules = load_taxonomy(categories_path).rules
        conn = connect(db_path)
        try:
            reapply_rules(conn, rules)
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return HTMLResponse(f'<span id="uncategorized-count">{count}</span>')

    @app.get("/import", response_class=HTMLResponse)
    async def import_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "import.html")

    @app.post("/import", response_class=HTMLResponse)
    async def import_upload(
        request: Request,
        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI's required pattern
    ) -> HTMLResponse:
        # Loaded once per request, not once per file: all files in one upload
        # see the same rule set, and an edit to categories.toml between
        # requests applies without restarting the app.
        rules = load_taxonomy(categories_path).rules
        # One connection for the whole upload; one file's failure (unknown
        # format) must not stop the others in the same request.
        conn = connect(db_path)
        try:
            results = [_import_one(conn, await f.read(), f.filename or "", rules) for f in files]
        finally:
            conn.close()
        return templates.TemplateResponse(request, "import_results.html", {"results": results})

    return app


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
