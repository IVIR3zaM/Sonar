"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from sonar.auth.settings import AuthSettings
from sonar.categorization.groups import LABELS as GROUP_LABELS
from sonar.categorization.groups import TRANSFER
from sonar.categorization.service import CategoryNotFound, RuleNotFound, reapply_stored_taxonomy
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.debts.store import DebtNotFound
from sonar.recurring.store import PaymentNotFound
from sonar.web import access, charts
from sonar.web.api import build_api_router
from sonar.web.display import cadence, days_until, display_date, eur
from sonar.web.pages import auth as auth_pages
from sonar.web.pages import (
    categories,
    dashboard,
    debts,
    import_,
    lights_on,
    monthly,
    recurring,
    settings,
    uncategorized,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _format_cents(cents: int) -> str:
    # Display-only conversion from integer cents; storage/comparisons never use float.
    sign = "-" if cents < 0 else ""
    whole, remainder = divmod(abs(cents), 100)
    return f"{sign}{whole}.{remainder:02d}"


def _format_percent(interest_bp: int | None) -> str:
    # A loan without interest_bp is amortized linearly; the page says so
    # instead of printing a rate that was never entered.
    return "linear" if interest_bp is None else f"{_format_cents(interest_bp)}%"


def _group_label(category_type: str | None) -> str | None:
    """The N02 spending-group label for a category row's badge; none for
    transfer and uncategorized rows, which the Monthly page badges skip.
    """
    if category_type is None or category_type == TRANSFER:
        return None
    return GROUP_LABELS.get(category_type)


templates.env.filters["money"] = _format_cents
templates.env.filters["percent"] = _format_percent
templates.env.filters["eur"] = eur
templates.env.filters["date"] = display_date
templates.env.filters["cadence"] = cadence
templates.env.filters["days_until"] = days_until
templates.env.filters["group_label"] = _group_label
# Chart macros call the pure geometry in sonar.web.charts rather than doing math in Jinja.
templates.env.globals["charts"] = charts


def create_app(
    db_path: Path = Path("data/sonar.db"),
    today: Callable[[], date] = date.today,
    auth: AuthSettings | None = None,
    google: auth_pages.GoogleClient | None = None,
) -> FastAPI:
    """Build the Sonar FastAPI app, migrating `db_path` on startup.

    The taxonomy (categories and rules) lives in the DB, not a file: the
    lifespan re-applies whatever is currently stored, so an edit made through
    the Categories page or the API takes effect without restarting the app.
    `today` defaults to the real clock; tests pin it so recurring-payment
    detection is deterministic.

    With `auth`, every page and API call needs a Google sign-in (SPEC §13
    Sign-in); `google` defaults to authlib's client, tests pass a fake.
    Without it no session or sign-in route exists at all.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = connect(db_path)
        try:
            apply_migrations(conn, MIGRATIONS_DIR)
            reapply_stored_taxonomy(conn, today())
        finally:
            conn.close()
        yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(build_api_router(db_path, today))
    app.include_router(dashboard.build_router(db_path, today, templates))
    app.include_router(monthly.build_router(db_path, today, templates))
    app.include_router(lights_on.build_router(db_path, today, templates))
    app.include_router(uncategorized.build_router(db_path, today, templates))
    app.include_router(import_.build_router(db_path, today, templates))
    app.include_router(recurring.build_router(db_path, today, templates))
    app.include_router(debts.build_router(db_path, today, templates))
    app.include_router(settings.build_router(db_path, today, templates))
    app.include_router(categories.build_router(db_path, today, templates))
    if auth is not None:
        google = google or auth_pages.google_client(auth)
        app.include_router(auth_pages.build_router(auth, google, templates))
        # Added last means outermost: the session must wrap the gate that reads it.
        app.add_middleware(
            BaseHTTPMiddleware, dispatch=access.sign_in_gate(db_path, templates, auth.api_token)
        )
        app.add_middleware(
            SessionMiddleware,
            secret_key=auth.session_secret,
            session_cookie=access.SESSION_COOKIE,
            max_age=access.SESSION_MAX_AGE,
            same_site="lax",
            https_only=auth.secure_cookies,
        )

    @app.exception_handler(PaymentNotFound)
    async def payment_not_found_handler(request: Request, exc: PaymentNotFound) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "error.html", {"message": f"No such payment: {exc}"}, status_code=404
        )

    @app.exception_handler(DebtNotFound)
    async def debt_not_found_handler(request: Request, exc: DebtNotFound) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "error.html", {"message": f"No such debt: {exc}"}, status_code=404
        )

    @app.exception_handler(CategoryNotFound)
    async def category_not_found_handler(request: Request, exc: CategoryNotFound) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "error.html", {"message": f"No such category: {exc}"}, status_code=404
        )

    @app.exception_handler(RuleNotFound)
    async def rule_not_found_handler(request: Request, exc: RuleNotFound) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "error.html", {"message": f"No such rule: {exc}"}, status_code=404
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> HTMLResponse | JSONResponse:
        # Only a 404 gets the styled page; other statuses (e.g. 405) keep
        # FastAPI's own response instead of hiding them behind "Page not found".
        if exc.status_code == 404:
            message = "That page or item does not exist."
            if request.url.path.startswith("/api/"):
                return JSONResponse({"error": message}, status_code=404)
            return templates.TemplateResponse(
                request, "error.html", {"message": message}, status_code=404
            )
        return await default_http_exception_handler(request, exc)

    return app
