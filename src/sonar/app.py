"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sonar.db import apply_migrations, connect

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

    return app
