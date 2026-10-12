"""The sign-in gate (SPEC §13 Sign-in): every page and API call needs an allowed session email.

Wired only when sign-in is configured; `/static/*` and `/auth/*` stay public so
the sign-in page can load. The allow-list is read on every request, so a
revoked email is locked out on its next request.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from contextlib import closing
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.auth.store import is_allowed
from sonar.db import connect

SESSION_COOKIE = "sonar_session"
SESSION_MAX_AGE = 14 * 24 * 60 * 60
LOGIN_PATH = "/auth/login"
PUBLIC_PREFIXES = ("/static/", "/auth/")

CallNext = Callable[[Request], Awaitable[Response]]


def sign_in_gate(
    db_path: Path, templates: Jinja2Templates, api_token: str | None = None
) -> Callable[[Request, CallNext], Awaitable[Response]]:
    """The dispatch function for a BaseHTTPMiddleware placed inside SessionMiddleware."""

    async def gate(request: Request, call_next: CallNext) -> Response:
        path = request.url.path
        if path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        is_api = path == "/api" or path.startswith("/api/")
        bearer = _bearer_token(request) if is_api and api_token else None
        if bearer is not None:
            # A machine credential: no session and no allow-list, and a wrong one is never
            # rescued by a session.
            if _same_token(bearer, api_token):
                return await call_next(request)
            return JSONResponse({"error": "Wrong API token."}, status_code=401)
        email = request.session.get("email")
        if email is None:
            if is_api:
                return JSONResponse({"error": "Sign in first."}, status_code=401)
            return RedirectResponse(LOGIN_PATH, status_code=302)
        if not _is_allowed(db_path, email):
            if is_api:
                return JSONResponse({"error": f"{email} is not allowed."}, status_code=403)
            return not_allowed_page(templates, request, email)
        # The shell's sidebar shows who is signed in.
        request.state.signed_in_email = email
        return await call_next(request)

    return gate


def not_allowed_page(
    templates: Jinja2Templates, request: Request, email: str | None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "not_allowed.html", {"email": email}, status_code=403
    )


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token if scheme.lower() == "bearer" else None


def _same_token(given: str, expected: str) -> bool:
    # Bytes, because comparing str raises on non-ASCII input.
    return hmac.compare_digest(given.encode(), expected.encode())


def _is_allowed(db_path: Path, email: str) -> bool:
    with closing(connect(db_path)) as conn:
        return is_allowed(conn, email)
