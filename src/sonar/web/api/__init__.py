"""JSON API under `/api` (SPEC §5, §6, §13): one module per area.

Each module is a thin HTTP translation over its feature's service or store and
exposes `build_router(db_path, today)`; `build_api_router` mounts them all.
`_common` holds the request-body parsing they share. The AGENTS.md
Categorization workflow reads and writes categories and rules here instead of
editing a file.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter

from sonar.web.api import categories, debts, recurring, settings


def build_api_router(db_path: Path, today: Callable[[], date]) -> APIRouter:
    """The `/api` router; included by `create_app` so every route shares its DB and clock."""
    router = APIRouter(prefix="/api")
    for module in (categories, recurring, debts, settings):
        router.include_router(module.build_router(db_path, today))
    return router
