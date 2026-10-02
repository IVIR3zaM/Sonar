"""JSON API for categories and rules (N17: SPEC §5, §13).

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
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError, field_validator

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

_JSON_CONTENT_TYPE = "application/json"


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

    return router
