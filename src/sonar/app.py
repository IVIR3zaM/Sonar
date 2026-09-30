"""FastAPI application factory."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from fractions import Fraction
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from sonar import charts, lights_on
from sonar.api import build_api_router
from sonar.categorization.export import build_categorization_request
from sonar.categorization.groups import LABELS as GROUP_LABELS
from sonar.categorization.groups import LIGHTS_ON, TRANSFER
from sonar.categorization.rules import Rule
from sonar.categorization.service import (
    GROUP_ORDER,
    CategoryNotFound,
    RuleNotFound,
    TaxonomyError,
    reapply_stored_taxonomy,
)
from sonar.categorization.service import add_category as add_category_service
from sonar.categorization.service import add_rule as add_rule_service
from sonar.categorization.service import delete_category as delete_category_service
from sonar.categorization.service import delete_rule as delete_rule_service
from sonar.categorization.service import list_categories as list_categories_view
from sonar.categorization.service import list_rules as list_rules_view
from sonar.categorization.service import move_rule as move_rule_service
from sonar.categorization.service import update_category as update_category_service
from sonar.categorization.service import update_rule as update_rule_service
from sonar.categorization.store import (
    load_stored_taxonomy,
    transactions_with_category,
    uncategorized_count,
    uncategorized_transactions,
)
from sonar.dashboard import load_dashboard
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.debt_store import DebtNotFound, add_debt, debt_overview, delete_debt, remaining_cents
from sonar.debts import Installment, Loan, MatchRule
from sonar.display import cadence, days_until, display_date, eur
from sonar.importing.importers import UnknownFormatError
from sonar.importing.store import import_file
from sonar.money import parse_basis_points, parse_cents, parse_signed_cents
from sonar.monthly import (
    UNCATEGORIZED,
    Period,
    adjacent_months,
    monthly_spending,
    only_category,
    parse_month,
    payment_months,
    period_for,
    salary_paydays,
)
from sonar.recurring.schedule import SchedulePeriod, next_due_date
from sonar.recurring.store import (
    PaymentNotFound,
    add_manual,
    dismiss,
    edit_payment,
    list_payments,
    pause_payment,
    resume_payment,
    sync_detected,
)
from sonar.settings_store import current_balance, load_settings, save_settings, set_manual_balance

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


def _nav_badge(count: int, oob: bool = False) -> str:
    macro = templates.get_template("components/nav_badge.html").module.nav_badge
    return str(macro(count, oob))


def _row_error(errors: dict, kind: str, row_id: int) -> dict | None:
    # Only the row whose form was actually submitted gets its error and kept
    # values; every other row on the page renders exactly as a fresh GET would.
    error = errors.get(kind)
    return error if error and error["id"] == row_id else None


# One hint per parser shape, not per field, since the format they accept
# (not the meaning of the field) is what the visitor needs to know.
_FIELD_HINTS = {
    "amount": "enter a number like 1234.56 or -250.50",
    "date": "pick a date",
    "int": "enter a whole number",
    "percent": "enter a percent like 3.5",
}


def _field(label: str, raw: str, kind: str, parser: Callable[[str], object]) -> object:
    """Parse one form field, replacing a parser's developer-facing message
    (e.g. "invalid literal for int() with base 10: 'x'") with one naming the
    field and the expected format.
    """
    try:
        return parser(raw)
    except ValueError:
        raise ValueError(f"{label}: {_FIELD_HINTS[kind]}") from None


# Domain modules (recurring/schedule.py, debts.py, settings_store.py) raise ValueErrors
# written for developers, e.g. "total must be positive, got -100". A needle
# found in that text maps to one sentence naming the field for the page;
# anything unmapped falls back to the raw message rather than hiding it.
_DOMAIN_ERROR_HINTS = {
    "salary_day must be between": "Salary day must be between 1 and 31.",
    "overdraft_limit_cents must not be positive": "Overdraft limit must be zero or negative.",
    "is in the future": "That date cannot be in the future.",
    "amount must be positive": "Amount must be positive.",
    "interval must be at least 1 month": "Interval must be at least 1 month.",
    "day must be within 1..31": "Day must be between 1 and 31.",
    "name must not be blank": "Name must not be blank.",
    "total must be positive": "Total must be positive.",
    "rate must be positive": "Rate must be positive.",
    "payments_count must be at least 1": "Number of payments must be at least 1.",
    "balance must be positive": "Balance must be positive.",
    "interest_bp must be positive when set": "Interest must be positive when set.",
    "value must not be blank": "Match value must not be blank.",
    "field must be one of": "Match field must be counterparty or mandate.",
}


def _friendly(error: ValueError) -> str:
    text = str(error)
    for needle, human in _DOMAIN_ERROR_HINTS.items():
        if needle in text:
            return human
    return text


def _group_label(category_type: str | None) -> str | None:
    """The N02 spending-group label for a category row's badge; none for
    transfer and uncategorized rows, which the Monthly page badges skip.
    """
    if category_type is None or category_type == TRANSFER:
        return None
    return GROUP_LABELS.get(category_type)


def _cents(amount: Fraction) -> int:
    # Half a cent rounds up, like lights_on.py's own rounding; these Fraction
    # amounts are never negative.
    return math.floor(amount + Fraction(1, 2))


def _lights_on_table_rows(
    months: list[lights_on.MonthSpend], categories: list[str], used: tuple[Period, ...]
) -> list[dict]:
    """One row per month, in cents, for the Keep-the-lights-on table."""
    return [
        {
            "period": m.period,
            "used": m.period in used,
            "total_cents": _cents(m.daily_lights_on),
            "by_category": {c: _cents(m.daily_by_category.get(c, Fraction(0))) for c in categories},
            "occasional_cents": _cents(m.daily_occasional),
        }
        for m in months
    ]


def _lights_on_chart_series(
    months: list[lights_on.MonthSpend], categories: list[str]
) -> list[dict]:
    """Total (if any category is set up) + one line per category + Occasional."""
    series = []
    if categories:
        series.append(
            {"name": "Keep the lights on", "values": [_cents(m.daily_lights_on) for m in months]}
        )
    series.extend(
        {
            "name": category,
            "values": [_cents(m.daily_by_category.get(category, Fraction(0))) for m in months],
        }
        for category in categories
    )
    series.append(
        {
            "name": "Occasional payments (not forecast)",
            "values": [_cents(m.daily_occasional) for m in months],
            "muted": True,
        }
    )
    return series


templates.env.filters["money"] = _format_cents
templates.env.filters["percent"] = _format_percent
templates.env.filters["eur"] = eur
templates.env.filters["date"] = display_date
templates.env.filters["cadence"] = cadence
templates.env.filters["days_until"] = days_until
templates.env.filters["group_label"] = _group_label
# Chart macros call the pure geometry in sonar.charts rather than doing math in Jinja.
templates.env.globals["charts"] = charts


def create_app(
    db_path: Path = Path("data/sonar.db"),
    today: Callable[[], date] = date.today,
) -> FastAPI:
    """Build the Sonar FastAPI app, migrating `db_path` on startup.

    The taxonomy (categories and rules) lives in the DB, not a file: the
    lifespan re-applies whatever is currently stored, so an edit made through
    the Categories page or the API takes effect without restarting the app.
    `today` defaults to the real clock; tests pin it so recurring-payment
    detection is deterministic.
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

    def _render_recurring_page(
        request: Request, status_code: int = 200, errors: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and every /recurring POST error path, so a
        # 400 re-render always shows the same page a fresh GET would.
        errors = errors or {}
        conn = connect(db_path)
        try:
            payments = list_payments(conn)
            # Inverted from debt_overview's debt -> payments so the payment row
            # can show which debt (if any) it is already counted as (SPEC §7).
            debt_names_by_payment_id = {
                payment.id: view.debt.name
                for view in debt_overview(conn, today())
                for payment in view.linked_payments
            }
            # periods come back ordered by starts_on, so [-1] is the latest.
            rows = [
                {
                    "payment": payment,
                    "latest": payment.periods[-1],
                    "next_due": next_due_date(payment.periods, payment.last_paid_date, today()),
                    "debt_name": debt_names_by_payment_id.get(payment.id),
                    "edit_error": _row_error(errors, "edit", payment.id),
                    "pause_error": _row_error(errors, "pause", payment.id),
                    "resume_error": _row_error(errors, "resume", payment.id),
                }
                for payment in payments
            ]
        finally:
            conn.close()
        return templates.TemplateResponse(
            request,
            "recurring.html",
            {"rows": rows, "add_error": errors.get("add")},
            status_code=status_code,
        )

    def _render_debts_page(
        request: Request, status_code: int = 200, errors: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and the two add-debt POST error paths.
        errors = errors or {}
        conn = connect(db_path)
        try:
            views = debt_overview(conn, today())
        finally:
            conn.close()
        installments = [v for v in views if isinstance(v.debt, Installment)]
        loans = [v for v in views if isinstance(v.debt, Loan)]
        # Shares the "one remaining figure per debt kind" rule with the
        # dashboard (SPEC §9 section 3) instead of re-deriving it here.
        total_remaining = sum(remaining_cents(v) for v in views)
        return templates.TemplateResponse(
            request,
            "debts.html",
            {
                "installments": installments,
                "loans": loans,
                "total_remaining": total_remaining,
                "installment_error": errors.get("installment"),
                "loan_error": errors.get("loan"),
            },
            status_code=status_code,
        )

    def _render_settings_page(
        request: Request, status_code: int = 200, error: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and both settings POST error paths.
        conn = connect(db_path)
        try:
            settings = load_settings(conn)
            balance = current_balance(conn)
        finally:
            conn.close()
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"settings": settings, "balance": balance, "today": today(), "error": error},
            status_code=status_code,
        )

    def _render_categories_page(
        request: Request, status_code: int = 200, errors: dict | None = None
    ) -> HTMLResponse:
        # Shared by the GET route and every /categories POST error path, so a
        # 400 re-render always shows the same page a fresh GET would.
        errors = errors or {}
        conn = connect(db_path)
        try:
            categories = list_categories_view(conn)
            rules = list_rules_view(conn)
        finally:
            conn.close()
        rows_by_group: dict[str, list[dict]] = {group: [] for group in GROUP_ORDER}
        for category in categories:
            rows_by_group[category.group].append(
                {
                    "category": category,
                    "edit_error": _row_error(errors, "edit", category.id),
                    "delete_error": _row_error(errors, "delete", category.id),
                }
            )
        sections = [
            {"group": group, "label": GROUP_LABELS[group], "rows": rows_by_group[group]}
            for group in GROUP_ORDER
        ]
        group_options = [(group, GROUP_LABELS[group]) for group in GROUP_ORDER]
        rule_rows = [
            {
                "rule": rule,
                "edit_error": _row_error(errors, "edit_rule", rule.id),
                "delete_error": _row_error(errors, "delete_rule", rule.id),
                "move_error": _row_error(errors, "move_rule", rule.id),
            }
            for rule in rules
        ]
        return templates.TemplateResponse(
            request,
            "categories.html",
            {
                "sections": sections,
                "group_options": group_options,
                "add_error": errors.get("add"),
                "rule_rows": rule_rows,
                "rule_count": len(rule_rows),
                "category_options": [(c.name, c.name) for c in categories],
                "sign_options": [("any", "Any"), ("debit", "Debit"), ("credit", "Credit")],
                "add_rule_error": errors.get("add_rule"),
            },
            status_code=status_code,
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            taxonomy = load_stored_taxonomy(conn)
            board = load_dashboard(conn, taxonomy.categories, today())
        finally:
            conn.close()
        return templates.TemplateResponse(request, "index.html", {"dashboard": board})

    @app.get("/monthly", response_class=HTMLResponse)
    async def monthly_page(
        request: Request, month: str | None = None, category: str | None = None
    ) -> HTMLResponse:
        conn = connect(db_path)
        try:
            taxonomy = load_stored_taxonomy(conn)
            rows = transactions_with_category(conn)
            salary_day = load_settings(conn).salary_day
        finally:
            conn.close()
        paydays = salary_paydays(rows)
        months = payment_months(rows, salary_day, paydays)
        if month is None:
            # The latest month with data rather than the clock's: exports are
            # often weeks old, and an empty current month would open the page.
            selected = months[0] if months else today().replace(day=1)
        else:
            try:
                selected = parse_month(month)
            except ValueError:
                raise StarletteHTTPException(status_code=404) from None
        older, newer = adjacent_months(months, selected)
        spending = monthly_spending(
            rows, taxonomy.categories, period_for(selected, salary_day, paydays)
        )
        # The category table always shows the whole month; only the payment
        # list below it narrows to the chosen category.
        category = category or None
        return templates.TemplateResponse(
            request,
            "monthly.html",
            {
                "spending": spending,
                "category": category,
                "category_label": "Uncategorized" if category == UNCATEGORIZED else category,
                "payments": (
                    only_category(spending.payments, category) if category else spending.payments
                ),
                "salary_months": salary_day is not None,
                "months": months,
                "older": older,
                "newer": newer,
            },
        )

    @app.get("/lights-on", response_class=HTMLResponse)
    async def lights_on_page(request: Request) -> HTMLResponse:
        conn = connect(db_path)
        try:
            taxonomy = load_stored_taxonomy(conn)
            rows = transactions_with_category(conn)
            salary_day = load_settings(conn).salary_day
            balance = current_balance(conn)
        finally:
            conn.close()
        categories = sorted(
            name for name, group in taxonomy.categories.items() if group == LIGHTS_ON
        )
        until = lights_on.last_known_day(rows, balance.as_of if balance else None)
        months = (
            []
            if until is None
            else lights_on.month_spends(rows, taxonomy.categories, salary_day, until)
        )
        shown = months[-24:]
        recent = lights_on.lights_on_forecast(months, 1)
        return templates.TemplateResponse(
            request,
            "lights_on.html",
            {
                "categories": categories,
                "months": shown,
                "chart_labels": [charts.month_label(m.period.month) for m in shown],
                "daily": recent,
                "salary_months": salary_day is not None,
                "table_rows": _lights_on_table_rows(
                    shown, categories, recent.months_used if recent else ()
                ),
                "chart_series": _lights_on_chart_series(shown, categories),
            },
        )

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

    @app.get("/uncategorized/badge", response_class=HTMLResponse)
    async def uncategorized_badge() -> HTMLResponse:
        conn = connect(db_path)
        try:
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return HTMLResponse(_nav_badge(count))

    @app.get("/import", response_class=HTMLResponse)
    async def import_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "import.html")

    @app.post("/import", response_class=HTMLResponse)
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

    @app.get("/recurring", response_class=HTMLResponse)
    async def recurring_page(request: Request) -> HTMLResponse:
        return _render_recurring_page(request)

    @app.post("/recurring")
    async def add_recurring(
        request: Request,
        name: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(...),
        starts_on: str = Form(...),
    ) -> HTMLResponse:
        try:
            period = SchedulePeriod(
                starts_on=_field("First due date", starts_on, "date", date.fromisoformat),
                until=None,
                amount_cents=_field("Amount", amount, "amount", parse_cents),
                interval_months=_field("Every (months)", interval_months, "int", int),
                day=_field("Day", day, "int", int),
            )
        except ValueError as error:
            values = {
                "name": name,
                "amount": amount,
                "interval_months": interval_months,
                "day": day,
                "starts_on": starts_on,
            }
            return _render_recurring_page(
                request,
                status_code=400,
                errors={"add": {"message": _friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            add_manual(conn, name, None, period)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/edit")
    async def edit_recurring(
        request: Request,
        id: int,
        name: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(...),
    ) -> HTMLResponse:
        try:
            amount_cents = _field("Amount", amount, "amount", parse_cents)
            interval = _field("Every (months)", interval_months, "int", int)
            day_number = _field("Day", day, "int", int)
            _validate_schedule(amount_cents, interval, day_number)
        except ValueError as error:
            values = {
                "name": name,
                "amount": amount,
                "interval_months": interval_months,
                "day": day,
            }
            return _render_recurring_page(
                request,
                status_code=400,
                errors={"edit": {"id": id, "message": _friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            edit_payment(conn, id, name, amount_cents, interval, day_number)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/dismiss")
    async def dismiss_recurring(id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            dismiss(conn, id)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/pause")
    async def pause_recurring(
        request: Request, id: int, last_date: str = Form(...)
    ) -> HTMLResponse:
        try:
            parsed_last_date = _field("Ends/pauses after", last_date, "date", date.fromisoformat)
        except ValueError as error:
            return _render_recurring_page(
                request,
                status_code=400,
                errors={
                    "pause": {
                        "id": id,
                        "message": _friendly(error),
                        "fields": {"last_date": last_date},
                    }
                },
            )
        conn = connect(db_path)
        try:
            pause_payment(conn, id, parsed_last_date)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.post("/recurring/{id}/resume")
    async def resume_recurring(
        request: Request,
        id: int,
        starts_on: str = Form(...),
        amount: str = Form(...),
        interval_months: str = Form(...),
        day: str = Form(""),
    ) -> HTMLResponse:
        try:
            parsed_starts_on = _field("Resumes on", starts_on, "date", date.fromisoformat)
            amount_cents = _field("Amount", amount, "amount", parse_cents)
            interval = _field("Every (months)", interval_months, "int", int)
            # Day defaults to the resume date's own day, same as schedule.resume_on.
            day_number = _field("Day", day, "int", int) if day else parsed_starts_on.day
            _validate_schedule(amount_cents, interval, day_number)
        except ValueError as error:
            values = {
                "starts_on": starts_on,
                "amount": amount,
                "interval_months": interval_months,
                "day": day,
            }
            return _render_recurring_page(
                request,
                status_code=400,
                errors={"resume": {"id": id, "message": _friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            resume_payment(conn, id, parsed_starts_on, amount_cents, interval, day_number)
        finally:
            conn.close()
        return RedirectResponse("/recurring", status_code=303)

    @app.get("/debts", response_class=HTMLResponse)
    async def debts_page(request: Request) -> HTMLResponse:
        return _render_debts_page(request)

    @app.post("/debts/installments")
    async def add_installment(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        name: str = Form(""),
        total: str = Form(""),
        rate: str = Form(""),
        interval_months: str = Form(""),
        first_payment_date: str = Form(""),
        payments_count: str = Form(""),
        match_field: str = Form(""),
        match_value: str = Form(""),
    ) -> HTMLResponse:
        try:
            debt = Installment(
                name=name,
                total_cents=_field("Total", total, "amount", parse_cents),
                rate_cents=_field("Rate", rate, "amount", parse_cents),
                interval_months=_field("Every N month(s)", interval_months, "int", int),
                first_payment_date=_field(
                    "First payment", first_payment_date, "date", date.fromisoformat
                ),
                payments_count=_field("Number of payments", payments_count, "int", int),
                match=MatchRule(match_field, match_value),
            )
        except ValueError as error:
            values = {
                "name": name,
                "total": total,
                "rate": rate,
                "interval_months": interval_months,
                "first_payment_date": first_payment_date,
                "payments_count": payments_count,
                "match_field": match_field,
                "match_value": match_value,
            }
            return _render_debts_page(
                request,
                status_code=400,
                errors={"installment": {"message": _friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            add_debt(conn, debt)
        finally:
            conn.close()
        return RedirectResponse("/debts", status_code=303)

    @app.post("/debts/loans")
    async def add_loan(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        name: str = Form(""),
        balance: str = Form(""),
        balance_as_of: str = Form(""),
        rate: str = Form(""),
        interest: str = Form(""),
        match_field: str = Form(""),
        match_value: str = Form(""),
    ) -> HTMLResponse:
        try:
            debt = Loan(
                name=name,
                balance_cents=_field("Balance", balance, "amount", parse_cents),
                balance_as_of=_field("As of", balance_as_of, "date", date.fromisoformat),
                rate_cents=_field("Monthly rate", rate, "amount", parse_cents),
                # An empty field means no interest was entered, not a 0% rate,
                # so the loan amortizes linearly (see amortization.loan_schedule).
                interest_bp=(
                    _field("Interest", interest, "percent", parse_basis_points)
                    if interest.strip()
                    else None
                ),
                match=MatchRule(match_field, match_value),
            )
        except ValueError as error:
            values = {
                "name": name,
                "balance": balance,
                "balance_as_of": balance_as_of,
                "rate": rate,
                "interest": interest,
                "match_field": match_field,
                "match_value": match_value,
            }
            return _render_debts_page(
                request,
                status_code=400,
                errors={"loan": {"message": _friendly(error), "fields": values}},
            )
        conn = connect(db_path)
        try:
            add_debt(conn, debt)
        finally:
            conn.close()
        return RedirectResponse("/debts", status_code=303)

    @app.post("/debts/{id}/delete")
    async def delete_debt_route(id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            delete_debt(conn, id)
        finally:
            conn.close()
        return RedirectResponse("/debts", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        return _render_settings_page(request)

    @app.post("/settings")
    async def update_settings(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        salary_day: str = Form(""),
        overdraft_limit: str = Form(""),
    ) -> HTMLResponse:
        values = {"salary_day": salary_day, "overdraft_limit": overdraft_limit}
        try:
            salary_day_number = _field("Salary day", salary_day, "int", int)
            overdraft_limit_cents = _field(
                "Overdraft limit", overdraft_limit, "amount", parse_signed_cents
            )
        except ValueError as error:
            return _render_settings_page(
                request,
                status_code=400,
                error={"form": "settings", "message": _friendly(error), "fields": values},
            )
        conn = connect(db_path)
        try:
            save_settings(conn, salary_day_number, overdraft_limit_cents)
        except ValueError as error:
            return _render_settings_page(
                request,
                status_code=400,
                error={"form": "settings", "message": _friendly(error), "fields": values},
            )
        finally:
            conn.close()
        return RedirectResponse("/settings", status_code=303)

    @app.post("/settings/balance")
    async def update_balance(
        request: Request,
        # Every field defaults to "" so an empty or missing value reaches our
        # own ValueError -> 400, not FastAPI's 422.
        amount: str = Form(""),
        as_of: str = Form(""),
    ) -> HTMLResponse:
        values = {"amount": amount, "as_of": as_of}
        try:
            amount_cents = _field("Amount", amount, "amount", parse_signed_cents)
            as_of_date = _field("As of", as_of, "date", date.fromisoformat)
        except ValueError as error:
            return _render_settings_page(
                request,
                status_code=400,
                error={"form": "balance", "message": _friendly(error), "fields": values},
            )
        conn = connect(db_path)
        try:
            set_manual_balance(conn, as_of_date, amount_cents, today())
        except ValueError as error:
            return _render_settings_page(
                request,
                status_code=400,
                error={"form": "balance", "message": _friendly(error), "fields": values},
            )
        finally:
            conn.close()
        return RedirectResponse("/settings", status_code=303)

    @app.get("/categories", response_class=HTMLResponse)
    async def categories_page(request: Request) -> HTMLResponse:
        return _render_categories_page(request)

    @app.post("/categories")
    async def add_category_route(
        request: Request, name: str = Form(...), group: str = Form(...)
    ) -> HTMLResponse:
        conn = connect(db_path)
        try:
            add_category_service(conn, today(), name, group)
        except TaxonomyError as error:
            return _render_categories_page(
                request,
                status_code=400,
                errors={
                    "add": {"message": error.message, "fields": {"name": name, "group": group}}
                },
            )
        finally:
            conn.close()
        return RedirectResponse("/categories", status_code=303)

    @app.post("/categories/{id}/edit")
    async def edit_category_route(
        request: Request, id: int, name: str = Form(...), group: str = Form(...)
    ) -> HTMLResponse:
        conn = connect(db_path)
        try:
            update_category_service(conn, today(), id, name, group)
        except TaxonomyError as error:
            return _render_categories_page(
                request,
                status_code=400,
                errors={
                    "edit": {
                        "id": id,
                        "message": error.message,
                        "fields": {"name": name, "group": group},
                    }
                },
            )
        finally:
            conn.close()
        return RedirectResponse("/categories", status_code=303)

    @app.post("/categories/{id}/delete")
    async def delete_category_route(request: Request, id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            delete_category_service(conn, today(), id)
        except TaxonomyError as error:
            return _render_categories_page(
                request,
                status_code=400,
                errors={"delete": {"id": id, "message": error.message, "fields": {}}},
            )
        finally:
            conn.close()
        return RedirectResponse("/categories", status_code=303)

    def _rule_form_fields(
        category: str,
        counterparty: str,
        counterparty_regex: str,
        purpose: str,
        purpose_regex: str,
        sign: str,
        iban: str,
        creditor_id: str,
        min_amount: str,
        max_amount: str,
        position: str,
    ) -> dict:
        return {
            "category": category,
            "counterparty": counterparty,
            "counterparty_regex": counterparty_regex,
            "purpose": purpose,
            "purpose_regex": purpose_regex,
            "sign": sign,
            "iban": iban,
            "creditor_id": creditor_id,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "position": position,
        }

    @app.post("/categories/rules")
    async def add_rule_route(
        request: Request,
        category: str = Form(""),
        counterparty: str = Form(""),
        counterparty_regex: str = Form(""),
        purpose: str = Form(""),
        purpose_regex: str = Form(""),
        sign: str = Form("any"),
        iban: str = Form(""),
        creditor_id: str = Form(""),
        min_amount: str = Form(""),
        max_amount: str = Form(""),
        position: str = Form(""),
    ) -> HTMLResponse:
        fields = _rule_form_fields(
            category,
            counterparty,
            counterparty_regex,
            purpose,
            purpose_regex,
            sign,
            iban,
            creditor_id,
            min_amount,
            max_amount,
            position,
        )
        conn = connect(db_path)
        try:
            add_rule_service(conn, today(), fields)
        except TaxonomyError as error:
            return _render_categories_page(
                request,
                status_code=400,
                errors={"add_rule": {"message": error.message, "fields": fields}},
            )
        finally:
            conn.close()
        return RedirectResponse("/categories#rules", status_code=303)

    @app.post("/categories/rules/{id}/edit")
    async def edit_rule_route(
        request: Request,
        id: int,
        category: str = Form(""),
        counterparty: str = Form(""),
        counterparty_regex: str = Form(""),
        purpose: str = Form(""),
        purpose_regex: str = Form(""),
        sign: str = Form("any"),
        iban: str = Form(""),
        creditor_id: str = Form(""),
        min_amount: str = Form(""),
        max_amount: str = Form(""),
        position: str = Form(""),
    ) -> HTMLResponse:
        fields = _rule_form_fields(
            category,
            counterparty,
            counterparty_regex,
            purpose,
            purpose_regex,
            sign,
            iban,
            creditor_id,
            min_amount,
            max_amount,
            position,
        )
        conn = connect(db_path)
        try:
            update_rule_service(conn, today(), id, fields)
        except TaxonomyError as error:
            return _render_categories_page(
                request,
                status_code=400,
                errors={"edit_rule": {"id": id, "message": error.message, "fields": fields}},
            )
        finally:
            conn.close()
        return RedirectResponse("/categories#rules", status_code=303)

    @app.post("/categories/rules/{id}/delete")
    async def delete_rule_route(request: Request, id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            delete_rule_service(conn, today(), id)
        finally:
            conn.close()
        return RedirectResponse("/categories#rules", status_code=303)

    @app.post("/categories/rules/{id}/move")
    async def move_rule_route(request: Request, id: int, position: str = Form("")) -> HTMLResponse:
        conn = connect(db_path)
        try:
            move_rule_service(conn, today(), id, position)
        except TaxonomyError as error:
            return _render_categories_page(
                request,
                status_code=400,
                errors={"move_rule": {"id": id, "message": error.message, "fields": {}}},
            )
        finally:
            conn.close()
        return RedirectResponse("/categories#rules", status_code=303)

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
