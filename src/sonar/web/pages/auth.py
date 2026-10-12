"""The Google sign-in pages (SPEC §13 Sign-in): login, the Google round trip, logout."""

from __future__ import annotations

from typing import Any, Protocol

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sonar.auth.settings import AuthSettings
from sonar.web.access import LOGIN_PATH, not_allowed_page

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


def build_router(auth: AuthSettings, google: GoogleClient, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/auth")

    def _login_page(request: Request, error: str | None = None, status_code: int = 200):
        return templates.TemplateResponse(
            request, "login.html", {"error": error}, status_code=status_code
        )

    @router.get("/login", response_class=HTMLResponse)
    async def login(request: Request) -> HTMLResponse:
        return _login_page(request)

    @router.get("/google")
    async def google_redirect(request: Request) -> Response:
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
        # Only the email may stay: authlib's state keys are spent once the token is in.
        request.session.clear()
        if userinfo.get("email_verified") is not True:
            return not_allowed_page(templates, request, userinfo.get("email"))
        request.session["email"] = userinfo["email"]
        # Always home, never a `next` parameter: no open redirect.
        return RedirectResponse("/", status_code=302)

    @router.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(LOGIN_PATH, status_code=302)

    return router
