"""JSON API for categories, rules and recurring payments (N17: SPEC §5, §6, §13).

Thin HTTP translation over `categorization.service`: every endpoint reads or
writes through its functions and nothing else, so validation, regex and
amount parsing exist in exactly one place (shared with the Categories page).
Also used by the AGENTS.md Categorization workflow, which reads and writes
categories and rules here instead of editing a file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from sonar.categorization.export import group_uncategorized
from sonar.categorization.service import (
    CategoryNotFound,
    RuleNotFound,
    TaxonomyError,
    add_category,
    add_rule,
    delete_category,
    delete_rule,
    list_categories,
    list_rules,
    move_rule,
    update_category,
    update_rule,
)
from sonar.categorization.store import uncategorized_count, uncategorized_transactions
from sonar.db import connect
from sonar.debts.model import Installment, InstallmentStatus, Loan, MatchRule
from sonar.debts.store import (
    DebtNotFound,
    DebtView,
    add_debt_closing_drafts,
    debt_overview,
    delete_debt,
    remaining_cents,
)
from sonar.recurring.store import (
    PaymentNotFound,
    RecurringPayment,
    get_payment,
    list_payments,
    update_details,
)
from sonar.web.forms import friendly

_JSON_CONTENT_TYPE = "application/json"

_INSTALLMENT_ONLY = ("total_cents", "interval_months", "first_payment_date", "payments_count")
_LOAN_ONLY = ("balance_cents", "balance_as_of", "interest_bp")
_INSTALLMENT_REQUIRED = (
    "name",
    "total_cents",
    "rate_cents",
    "interval_months",
    "first_payment_date",
    "payments_count",
    "match_field",
    "match_value",
)
_LOAN_REQUIRED = (
    "name",
    "balance_cents",
    "balance_as_of",
    "rate_cents",
    "match_field",
    "match_value",
)
_DATE_FIELDS = ("first_payment_date", "balance_as_of")
# Which request field a domain error belongs to, found by its message text.
_DOMAIN_ERROR_FIELDS = {
    "name must not be blank": "name",
    "total must be positive": "total_cents",
    "rate must be positive": "rate_cents",
    "interval must be at least 1 month": "interval_months",
    "payments_count must be at least 1": "payments_count",
    "balance must be positive": "balance_cents",
    "interest_bp must be positive when set": "interest_bp",
    "field must be one of": "match_field",
    "value must not be blank": "match_value",
}


class _StrictModel(BaseModel):
    """Every field optional text or null; an unknown field is a typo, not data."""

    model_config = ConfigDict(extra="forbid")


def _numeric_as_text(value: object) -> object:
    # JSON senders may write position/amount as a number; pass it on as the
    # text `categorization.service` already parses, so both shapes work the same.
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return value


class CategoryIn(_StrictModel):
    name: str | None = None
    group: str | None = None
    debt: StrictBool | None = None


class RuleIn(_StrictModel):
    category: str | None = None
    counterparty: str | None = None
    counterparty_regex: str | None = None
    purpose: str | None = None
    purpose_regex: str | None = None
    sign: str | None = None
    iban: str | None = None
    creditor_id: str | None = None
    min_amount: str | int | float | None = None
    max_amount: str | int | float | None = None
    position: str | int | None = None

    @field_validator("min_amount", "max_amount", "position", mode="before")
    @classmethod
    def _stringify(cls, value: object) -> object:
        return _numeric_as_text(value)


class MoveIn(_StrictModel):
    position: str | int | None = None

    @field_validator("position", mode="before")
    @classmethod
    def _stringify(cls, value: object) -> object:
        return _numeric_as_text(value)


class RecurringIn(_StrictModel):
    name: str | None = None
    description: str | None = None


class DebtIn(_StrictModel):
    kind: StrictStr | None = None
    name: StrictStr | None = None
    match_field: StrictStr | None = None
    match_value: StrictStr | None = None
    first_payment_date: StrictStr | None = None
    balance_as_of: StrictStr | None = None
    total_cents: StrictInt | None = None
    rate_cents: StrictInt | None = None
    interval_months: StrictInt | None = None
    payments_count: StrictInt | None = None
    balance_cents: StrictInt | None = None
    interest_bp: StrictInt | None = None


async def _parse_body(request: Request, model_cls: type[BaseModel]) -> BaseModel | JSONResponse:
    """The body as a `model_cls` instance, or the 415/422 response to return in its place."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != _JSON_CONTENT_TYPE:
        return JSONResponse({"error": "Content-Type must be application/json"}, status_code=415)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Body is not valid JSON"}, status_code=422)
    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Invalid request body", "details": "expected a JSON object"}, status_code=422
        )
    try:
        return model_cls(**payload)
    except ValidationError as error:
        return JSONResponse(
            {"error": "Invalid request body", "details": error.errors()}, status_code=422
        )


def _recurring_item(payment: RecurringPayment) -> dict:
    latest = payment.periods[-1]
    return {
        "id": payment.id,
        "detection_key": payment.detection_key,
        "name": payment.name,
        "description": payment.description,
        "category": payment.category,
        "status": payment.status,
        "amount_cents": latest.amount_cents,
        "interval_months": latest.interval_months,
        "day": latest.day,
    }


def _debt_item(view: DebtView) -> dict:
    debt, status = view.debt, view.status
    item: dict = {
        "id": view.id,
        "kind": "installment" if isinstance(debt, Installment) else "loan",
        "name": debt.name,
        "match_field": debt.match.field,
        "match_value": debt.match.value,
        "rate_cents": debt.rate_cents,
        "total_cents": None,
        "interval_months": None,
        "first_payment_date": None,
        "payments_count": None,
        "balance_cents": None,
        "balance_as_of": None,
        "interest_bp": None,
        "remaining_cents": remaining_cents(view),
        "paid_off": status.paid_off,
        "linked_payment_ids": sorted(p.id for p in view.linked_payments),
    }
    if isinstance(debt, Installment) and isinstance(status, InstallmentStatus):
        item |= {
            "total_cents": debt.total_cents,
            "interval_months": debt.interval_months,
            "first_payment_date": debt.first_payment_date.isoformat(),
            "payments_count": debt.payments_count,
            "paid_cents": status.paid_cents,
            "payments_remaining": status.payments_remaining,
            "end_date": status.end_date.isoformat(),
        }
    elif isinstance(debt, Loan) and not isinstance(status, InstallmentStatus):
        payoff = status.payoff_date
        item |= {
            "balance_cents": debt.balance_cents,
            "balance_as_of": debt.balance_as_of.isoformat(),
            "interest_bp": debt.interest_bp,
            "paid_cents": status.paid_since_statement_cents,
            "payments_remaining": None,
            "end_date": payoff.isoformat() if payoff else None,
        }
    return {key: item[key] for key in _DEBT_ITEM_KEYS}


_DEBT_ITEM_KEYS = (
    "id",
    "kind",
    "name",
    "match_field",
    "match_value",
    "rate_cents",
    "total_cents",
    "interval_months",
    "first_payment_date",
    "payments_count",
    "balance_cents",
    "balance_as_of",
    "interest_bp",
    "paid_cents",
    "remaining_cents",
    "payments_remaining",
    "end_date",
    "paid_off",
    "linked_payment_ids",
)


def _bad_debt(error: str, field: str) -> JSONResponse:
    return JSONResponse({"error": error, "field": field}, status_code=400)


def _build_debt(body: DebtIn) -> Installment | Loan | JSONResponse:
    """The domain debt for `body`, or the 400 naming the first field that is wrong."""
    if body.kind not in ("installment", "loan"):
        return _bad_debt("kind must be installment or loan", "kind")
    installment = body.kind == "installment"
    for key in _LOAN_ONLY if installment else _INSTALLMENT_ONLY:
        if getattr(body, key) is not None:
            return _bad_debt(f"{key} does not belong to an {body.kind}", key)
    for key in _INSTALLMENT_REQUIRED if installment else _LOAN_REQUIRED:
        if getattr(body, key) is None:
            return _bad_debt(f"{key} is required", key)
    dates: dict[str, date] = {}
    for key in _DATE_FIELDS:
        text = getattr(body, key)
        if text is None:
            continue
        try:
            dates[key] = date.fromisoformat(text)
        except ValueError:
            return _bad_debt(f"{key} must be a date like 2026-01-31", key)
    try:
        match = MatchRule(body.match_field, body.match_value)
        if installment:
            return Installment(
                name=body.name,
                total_cents=body.total_cents,
                rate_cents=body.rate_cents,
                interval_months=body.interval_months,
                first_payment_date=dates["first_payment_date"],
                payments_count=body.payments_count,
                match=match,
            )
        return Loan(
            name=body.name,
            balance_cents=body.balance_cents,
            balance_as_of=dates["balance_as_of"],
            rate_cents=body.rate_cents,
            interest_bp=body.interest_bp,
            match=match,
        )
    except ValueError as error:
        field = next((f for needle, f in _DOMAIN_ERROR_FIELDS.items() if needle in str(error)), "")
        return _bad_debt(friendly(error), field)


def build_api_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    """The `/api` router; included by `create_app` so every route shares its DB and clock."""
    router = APIRouter(prefix="/api")

    def _category_item(conn, category_id: int) -> dict:
        for item in list_categories(conn):
            if item.id == category_id:
                return asdict(item)
        raise CategoryNotFound(category_id)

    def _rule_item(conn, rule_id: int) -> dict:
        for item in list_rules(conn):
            if item.id == rule_id:
                return asdict(item)
        raise RuleNotFound(rule_id)

    @router.get("/categories")
    async def get_categories() -> JSONResponse:
        conn = connect(db_path)
        try:
            items = [asdict(item) for item in list_categories(conn)]
        finally:
            conn.close()
        return JSONResponse(items)

    @router.post("/categories", status_code=201)
    async def post_category(request: Request) -> JSONResponse:
        body = await _parse_body(request, CategoryIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            try:
                category_id = add_category(
                    conn, today(), body.name or "", body.group or "", bool(body.debt)
                )
            except TaxonomyError as error:
                return JSONResponse({"error": error.message, "field": error.field}, status_code=400)
            item = _category_item(conn, category_id)
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return JSONResponse({**item, "uncategorized": count}, status_code=201)

    @router.put("/categories/{id}")
    async def put_category(id: int, request: Request) -> JSONResponse:
        body = await _parse_body(request, CategoryIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            try:
                update_category(conn, today(), id, body.name or "", body.group or "", body.debt)
            except TaxonomyError as error:
                return JSONResponse({"error": error.message, "field": error.field}, status_code=400)
            except CategoryNotFound as error:
                return JSONResponse({"error": f"No such category: {error}"}, status_code=404)
            item = _category_item(conn, id)
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return JSONResponse({**item, "uncategorized": count})

    @router.delete("/categories/{id}")
    async def delete_category_route(id: int) -> JSONResponse:
        conn = connect(db_path)
        try:
            try:
                item = _category_item(conn, id)
            except CategoryNotFound as error:
                return JSONResponse({"error": f"No such category: {error}"}, status_code=404)
            try:
                delete_category(conn, today(), id)
            except TaxonomyError as error:
                return JSONResponse({"error": error.message, "field": error.field}, status_code=400)
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return JSONResponse({**item, "uncategorized": count})

    @router.get("/rules")
    async def get_rules() -> JSONResponse:
        conn = connect(db_path)
        try:
            items = [asdict(item) for item in list_rules(conn)]
        finally:
            conn.close()
        return JSONResponse(items)

    @router.post("/rules", status_code=201)
    async def post_rule(request: Request) -> JSONResponse:
        body = await _parse_body(request, RuleIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            try:
                rule_id = add_rule(conn, today(), body.model_dump())
            except TaxonomyError as error:
                return JSONResponse({"error": error.message, "field": error.field}, status_code=400)
            item = _rule_item(conn, rule_id)
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return JSONResponse({**item, "uncategorized": count}, status_code=201)

    @router.put("/rules/{id}")
    async def put_rule(id: int, request: Request) -> JSONResponse:
        body = await _parse_body(request, RuleIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            try:
                update_rule(conn, today(), id, body.model_dump())
            except TaxonomyError as error:
                return JSONResponse({"error": error.message, "field": error.field}, status_code=400)
            except RuleNotFound as error:
                return JSONResponse({"error": f"No such rule: {error}"}, status_code=404)
            item = _rule_item(conn, id)
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return JSONResponse({**item, "uncategorized": count})

    @router.delete("/rules/{id}")
    async def delete_rule_route(id: int) -> JSONResponse:
        conn = connect(db_path)
        try:
            try:
                item = _rule_item(conn, id)
            except RuleNotFound as error:
                return JSONResponse({"error": f"No such rule: {error}"}, status_code=404)
            delete_rule(conn, today(), id)
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return JSONResponse({**item, "uncategorized": count})

    @router.post("/rules/{id}/move")
    async def move_rule_route(id: int, request: Request) -> JSONResponse:
        body = await _parse_body(request, MoveIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            try:
                move_rule(conn, today(), id, body.position or "")
            except TaxonomyError as error:
                return JSONResponse({"error": error.message, "field": error.field}, status_code=400)
            except RuleNotFound as error:
                return JSONResponse({"error": f"No such rule: {error}"}, status_code=404)
            rules = [asdict(item) for item in list_rules(conn)]
            count = uncategorized_count(conn)
        finally:
            conn.close()
        return JSONResponse({"rules": rules, "uncategorized": count})

    @router.get("/uncategorized")
    async def get_uncategorized() -> JSONResponse:
        conn = connect(db_path)
        try:
            txs = uncategorized_transactions(conn)
        finally:
            conn.close()
        groups = group_uncategorized(txs)
        return JSONResponse(
            {
                "count": len(txs),
                "groups": [
                    {
                        "counterparty": group.key,
                        "count": group.count,
                        "min_amount": group.min_amount,
                        "max_amount": group.max_amount,
                        "first_date": group.first_date.isoformat(),
                        "last_date": group.last_date.isoformat(),
                        "sample_purposes": group.sample_purposes,
                    }
                    for group in groups
                ],
            }
        )

    @router.get("/recurring")
    async def get_recurring() -> JSONResponse:
        conn = connect(db_path)
        try:
            items = [_recurring_item(p) for p in list_payments(conn, include_dismissed=True)]
        finally:
            conn.close()
        return JSONResponse(items)

    @router.put("/recurring/{id}")
    async def put_recurring(id: int, request: Request) -> JSONResponse:
        body = await _parse_body(request, RecurringIn)
        if isinstance(body, JSONResponse):
            return body
        conn = connect(db_path)
        try:
            try:
                current = get_payment(conn, id)
            except PaymentNotFound:
                return JSONResponse({"error": f"No such recurring payment: {id}"}, status_code=404)
            name = (body.name or "").strip() if "name" in body.model_fields_set else current.name
            if not name:
                return JSONResponse(
                    {"error": "Name must not be blank", "field": "name"}, status_code=400
                )
            description = (
                body.description if "description" in body.model_fields_set else current.description
            )
            update_details(conn, id, name, description)
            item = _recurring_item(get_payment(conn, id))
        finally:
            conn.close()
        return JSONResponse(item)

    def _find_debt(conn, debt_id: int) -> DebtView:
        for view in debt_overview(conn, today()):
            if view.id == debt_id:
                return view
        raise DebtNotFound(debt_id)

    @router.get("/debts")
    async def get_debts() -> JSONResponse:
        conn = connect(db_path)
        try:
            items = [_debt_item(view) for view in debt_overview(conn, today())]
        finally:
            conn.close()
        return JSONResponse(items)

    @router.post("/debts", status_code=201)
    async def post_debt(request: Request) -> JSONResponse:
        body = await _parse_body(request, DebtIn)
        if isinstance(body, JSONResponse):
            return body
        debt = _build_debt(body)
        if isinstance(debt, JSONResponse):
            return debt
        conn = connect(db_path)
        try:
            item = _debt_item(_find_debt(conn, add_debt_closing_drafts(conn, debt)))
        finally:
            conn.close()
        return JSONResponse(item, status_code=201)

    @router.delete("/debts/{id}")
    async def delete_debt_route(id: int) -> JSONResponse:
        conn = connect(db_path)
        try:
            try:
                item = _debt_item(_find_debt(conn, id))
            except DebtNotFound:
                return JSONResponse({"error": f"No such debt: {id}"}, status_code=404)
            delete_debt(conn, id)
        finally:
            conn.close()
        return JSONResponse(item)

    return router
