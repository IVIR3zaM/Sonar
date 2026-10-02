"""A stand-in for authlib's Google client so sign-in tests never touch the network."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuthError
from starlette.requests import Request
from starlette.responses import RedirectResponse

GOOGLE_AUTHORIZE_URL = "https://accounts.example.com/authorize"


class FakeGoogle:
    def __init__(self) -> None:
        self.userinfo: dict = {}
        self.error: OAuthError | None = None
        self.redirect_uris: list[str] = []

    def signs_in(self, email: str, email_verified: bool | None = True) -> None:
        self.userinfo = {"email": email}
        if email_verified is not None:
            self.userinfo["email_verified"] = email_verified

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> RedirectResponse:
        # authlib keeps its OAuth state in the session; the callback must drop it.
        request.session["_state_google_fake"] = {"data": {"redirect_uri": redirect_uri}}
        self.redirect_uris.append(redirect_uri)
        return RedirectResponse(GOOGLE_AUTHORIZE_URL, status_code=302)

    async def authorize_access_token(self, request: Request) -> dict:
        if self.error is not None:
            raise self.error
        return {"userinfo": dict(self.userinfo)}
