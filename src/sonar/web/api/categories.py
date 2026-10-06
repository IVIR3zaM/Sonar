"""Categories, rules, uncategorized and reapply endpoints (SPEC §5, §13).

Every endpoint reads or writes through `categorization.service`, so validation,
regex and amount parsing exist in exactly one place (shared with the
Categories page).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StrictBool, field_validator

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
    reapply_stored_taxonomy,
    update_category,
    update_rule,
)
from sonar.categorization.store import uncategorized_count, uncategorized_transactions
from sonar.db import connect
from sonar.web.api._common import _numeric_as_text, _parse_body, _StrictModel


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


def build_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    router = APIRouter()

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

    @router.post("/reapply")
    async def reapply() -> JSONResponse:
        conn = connect(db_path)
        try:
            count = reapply_stored_taxonomy(conn, today())
        finally:
            conn.close()
        return JSONResponse({"uncategorized": count})

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
