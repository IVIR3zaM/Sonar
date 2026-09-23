"""FastAPI application factory."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.categorize import Rule, load_taxonomy
from sonar.categorizing import reapply_rules, uncategorized_count, uncategorized_transactions
from sonar.db import apply_migrations, connect
from sonar.importers import UnknownFormatError
from sonar.importing import import_file
from sonar.money import parse_cents
from sonar.recurring import (
    PaymentNotFound,
    add_manual,
    dismiss,
    edit_payment,
    list_payments,
    pause_payment,
    resume_payment,
    sync_detected,
)
from sonar.schedule import SchedulePeriod, next_due_date
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
    today: Callable[[], date] = date.today,
) -> FastAPI:
    """Build the Sonar FastAPI app, migrating `db_path` on startup.

    `categories_path` is read fresh on every import and again at startup, so
    editing `categories.toml` by hand (the Categorization workflow) takes
    effect without restarting the app. `today` defaults to the real clock;
    tests pin it so recurring-payment detection is deterministic.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = connect(db_path)
        try:
            apply_migrations(conn, MIGRATIONS_DIR)
            taxonomy = load_taxonomy(categories_path)
            reapply_rules(conn, taxonomy.rules)
            sync_detected(conn, taxonomy.categories, today())
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
        taxonomy = load_taxonomy(categories_path)
        conn = connect(db_path)
        try:
            reapply_rules(conn, taxonomy.rules)
            sync_detected(conn, taxonomy.categories, today())
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
        taxonomy = load_taxonomy(categories_path)
        # One connection for the whole upload; one file's failure (unknown
        # format) must not stop the others in the same request.
        conn = connect(db_path)
        try:
            results = [
                _import_one(conn, await f.read(), f.filename or "", taxonomy.rules) for f in files
            ]
            # Once per request, after every file, so detection sees the full upload.
            sync_detected(conn, taxonomy.categories, today())
        finally:
            conn.close()
        return templates.TemplateResponse(request, "import_results.html", {"results": results})

    @app.get("/recurring", response_class=HTMLResponse)
    async def recurring_page(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            payments = list_payments(conn)
            # periods come back ordered by starts_on, so [-1] is the latest.
            rows = [
                {
                    "payment": payment,
                    "latest": payment.periods[-1],
                    "next_due": next_due_date(payment.periods, payment.last_paid_date, today()),
                }
                for payment in payments
            ]
        finally:
            conn.close()
        return templates.TemplateResponse(request, "recurring.html", {"rows": rows})

    @app.post("/recurring")
    async def add_recurring(
        name: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(...),
        starts_on: str = Form(...),
    ) -> HTMLResponse:
        try:
            period = SchedulePeriod(
                starts_on=date.fromisoformat(starts_on),
                until=None,
                amount_cents=parse_cents(amount),
                interval_months=int(interval_months),
                day=int(day),
            )
        except ValueError as error:
            return HTMLResponse(str(error), status_code=400)
        conn = connect(db_path)
        try:
            add_manual(conn, name, None, period)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/edit")
    async def edit_recurring(
        id: int,
        name: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(...),
    ) -> HTMLResponse:
        try:
            amount_cents = parse_cents(amount)
            interval = int(interval_months)
            day_number = int(day)
            _validate_schedule(amount_cents, interval, day_number)
        except ValueError as error:
            return HTMLResponse(str(error), status_code=400)
        conn = connect(db_path)
        try:
            edit_payment(conn, id, name, amount_cents, interval, day_number)
        except PaymentNotFound:
            return HTMLResponse(f"No such payment: {id}", status_code=404)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/dismiss")
    async def dismiss_recurring(id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            dismiss(conn, id)
        except PaymentNotFound:
            return HTMLResponse(f"No such payment: {id}", status_code=404)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/pause")
    async def pause_recurring(id: int, last_date: str = Form(...)) -> HTMLResponse:
        try:
            parsed_last_date = date.fromisoformat(last_date)
        except ValueError as error:
            return HTMLResponse(str(error), status_code=400)
        conn = connect(db_path)
        try:
            pause_payment(conn, id, parsed_last_date)
        except PaymentNotFound:
            return HTMLResponse(f"No such payment: {id}", status_code=404)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/resume")
    async def resume_recurring(
        id: int,
        starts_on: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(""),
    ) -> HTMLResponse:
        try:
            parsed_starts_on = date.fromisoformat(starts_on)
            amount_cents = parse_cents(amount)
            interval = int(interval_months)
            # Day defaults to the resume date's own day, same as schedule.resume_on.
            day_number = int(day) if day else parsed_starts_on.day
            _validate_schedule(amount_cents, interval, day_number)
        except ValueError as error:
            return HTMLResponse(str(error), status_code=400)
        conn = connect(db_path)
        try:
            resume_payment(conn, id, parsed_starts_on, amount_cents, interval, day_number)
        except PaymentNotFound:
            return HTMLResponse(f"No such payment: {id}", status_code=404)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    return app


def _validate_schedule(amount_cents: int, interval_months: int, day: int) -> None:
    # Reuses SchedulePeriod's own checks instead of duplicating them; the
    # starts_on value here is a placeholder, only used to satisfy the dataclass.
    SchedulePeriod(
        starts_on=date(2000, 1, 1),
        until=None,
        amount_cents=amount_cents,
        interval_months=interval_months,
        day=day,
    )


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
