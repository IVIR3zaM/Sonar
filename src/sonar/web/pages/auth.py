"""The Google sign-in pages (SPEC §13 Sign-in): login, the Google round trip, logout."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.auth.codes import SignInCodes, TooManyAttempts
from sonar.auth.settings import AuthSettings
from sonar.web.access import LOGIN_PATH, is_allowed_email, not_allowed_page

CODE_MODE = "code"
CODE_MODE_KEY = "code_mode"
CODE_ERROR = "That code did not work. Sign in with Google again to get a new one."
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


class GoogleClient(Protocol):
    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response: ...

    async def authorize_access_token(self, request: Request) -> dict[str, Any]: ...


def google_client(auth: AuthSettings) -> GoogleClient:
    """authlib's OpenID Connect client for Google; discovery is fetched lazily, on first sign-in."""
    oauth = OAuth()
    oauth.register(
        "google",
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_id=auth.google_client_id,
        client_secret=auth.google_client_secret,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth.google


def build_router(
    auth: AuthSettings,
    google: GoogleClient,
    templates: Jinja2Templates,
    codes: SignInCodes,
    db_path: Path,
    now: Callable[[], datetime],
) -> APIRouter:
    router = APIRouter(prefix="/auth")

    def _login_page(
        request: Request,
        error: str | None = None,
        status_code: int = 200,
        code_error: str | None = None,
        code_value: str = "",
    ):
        context = {"error": error, "code_error": code_error, "code_value": code_value}
        return templates.TemplateResponse(request, "login.html", context, status_code=status_code)

    def _code_rejected(request: Request, code: str, status_code: int):
        return _login_page(request, status_code=status_code, code_error=CODE_ERROR, code_value=code)

    def _from_this_site(request: Request) -> bool:
        # A cross-site form post must not be able to sign a victim's browser in as someone else.
        origin = request.headers.get("origin")
        if origin is not None:
            return origin == _origin(auth.base_url)
        return request.headers.get("referer", "").startswith(f"{auth.base_url}/")

    def _code_page(request: Request, email: str) -> Response:
        if not is_allowed_email(db_path, email):
            return not_allowed_page(templates, request, email)
        response = templates.TemplateResponse(
            request, "sign_in_code.html", {"code": codes.issue(email, now())}
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/login", response_class=HTMLResponse)
    async def login(request: Request) -> HTMLResponse:
        return _login_page(request)

    @router.get("/google")
    async def google_redirect(request: Request, mode: str | None = None) -> Response:
        # Code mode ends on a one-time code page instead of a session (home-screen apps).
        if mode == CODE_MODE:
            request.session[CODE_MODE_KEY] = True
        else:
            request.session.pop(CODE_MODE_KEY, None)
        return await google.authorize_redirect(request, f"{auth.base_url}/auth/callback")

    @router.get("/callback")
    async def callback(request: Request) -> Response:
        try:
            token = await google.authorize_access_token(request)
        except OAuthError:
            request.session.clear()
            return _login_page(
                request, error="Google sign-in did not complete. Try again.", status_code=400
            )
        userinfo = token.get("userinfo") or {}
        code_mode = request.session.get(CODE_MODE_KEY) is True
        # Only the email may stay: authlib's state keys are spent once the token is in.
        request.session.clear()
        if userinfo.get("email_verified") is not True:
            return not_allowed_page(templates, request, userinfo.get("email"))
        if code_mode:
            return _code_page(request, userinfo["email"])
        request.session["email"] = userinfo["email"]
        # Always home, never a `next` parameter: no open redirect.
        return RedirectResponse("/", status_code=302)

    @router.post("/code")
    async def exchange_code(request: Request, code: str = Form("")) -> Response:
        # Checked before redeem so a foreign post costs the owner no attempt.
        if not _from_this_site(request):
            return _code_rejected(request, code, status_code=403)
        client = request.client.host if request.client else ""
        try:
            email = codes.redeem(code, client, now())
        except TooManyAttempts:
            return _code_rejected(request, code, status_code=429)
        # The code was valid when issued; the allow-list is read again now.
        if email is None or not is_allowed_email(db_path, email):
            return _code_rejected(request, code, status_code=400)
        request.session.clear()
        request.session["email"] = email
        return RedirectResponse("/", status_code=303)

    @router.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(LOGIN_PATH, status_code=302)

    return router


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
