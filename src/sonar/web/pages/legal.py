"""The public privacy and terms pages (SPEC §13 Sign-in, Public pages): static text, no data."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def build_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/privacy", response_class=HTMLResponse)
    async def privacy(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "privacy.html")

    @router.get("/terms", response_class=HTMLResponse)
    async def terms(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "terms.html")

    return router
