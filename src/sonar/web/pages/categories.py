"""The categories and rules page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.categorization.groups import LABELS as GROUP_LABELS
from sonar.categorization.service import GROUP_ORDER, TaxonomyError
from sonar.categorization.service import add_category as add_category_service
from sonar.categorization.service import add_rule as add_rule_service
from sonar.categorization.service import delete_category as delete_category_service
from sonar.categorization.service import delete_rule as delete_rule_service
from sonar.categorization.service import list_categories as list_categories_view
from sonar.categorization.service import list_rules as list_rules_view
from sonar.categorization.service import move_rule as move_rule_service
from sonar.categorization.service import update_category as update_category_service
from sonar.categorization.service import update_rule as update_rule_service
from sonar.db import connect
from sonar.web import forms


def build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

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
                    "edit_error": forms.row_error(errors, "edit", category.id),
                    "delete_error": forms.row_error(errors, "delete", category.id),
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
                "edit_error": forms.row_error(errors, "edit_rule", rule.id),
                "delete_error": forms.row_error(errors, "delete_rule", rule.id),
                "move_error": forms.row_error(errors, "move_rule", rule.id),
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

    @router.get("/categories", response_class=HTMLResponse)
    async def categories_page(request: Request) -> HTMLResponse:
        return _render_categories_page(request)

    @router.post("/categories")
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

    @router.post("/categories/{id}/edit")
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

    @router.post("/categories/{id}/delete")
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

    @router.post("/categories/rules")
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

    @router.post("/categories/rules/{id}/edit")
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

    @router.post("/categories/rules/{id}/delete")
    async def delete_rule_route(request: Request, id: int) -> HTMLResponse:
        conn = connect(db_path)
        try:
            delete_rule_service(conn, today(), id)
        finally:
            conn.close()
        return RedirectResponse("/categories#rules", status_code=303)

    @router.post("/categories/rules/{id}/move")
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

    return router
