"""Sign-in settings (SPEC §13 Sign-in): Google sign-in is on only when all four are set.

Pure: the caller passes the environment, so only `__main__` ever reads `os.environ`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

AUTH_ENV_VARS = (
    "SONAR_GOOGLE_CLIENT_ID",
    "SONAR_GOOGLE_CLIENT_SECRET",
    "SONAR_SESSION_SECRET",
    "SONAR_BASE_URL",
)


@dataclass(frozen=True)
class AuthSettings:
    google_client_id: str
    google_client_secret: str
    session_secret: str
    base_url: str
    # Optional machine credential for /api/*; not one of the four that switch sign-in on.
    api_token: str | None = None

    @property
    def secure_cookies(self) -> bool:
        # A Secure cookie is never sent over plain http, so local http runs would loop to login.
        return self.base_url.startswith("https://")


def auth_settings(env: Mapping[str, str]) -> AuthSettings | None:
    """The sign-in settings in `env`; None when none is set.

    An empty value counts as unset. A partial set raises ValueError naming the
    missing variables: half-configured sign-in must never silently mean "no sign-in".
    """
    client_id, client_secret, session_secret, base_url = (
        env.get(name, "") for name in AUTH_ENV_VARS
    )
    missing = [name for name in AUTH_ENV_VARS if not env.get(name, "")]
    if len(missing) == len(AUTH_ENV_VARS):
        return None
    if missing:
        raise ValueError(f"Google sign-in is only partly configured; missing: {', '.join(missing)}")
    return AuthSettings(
        google_client_id=client_id,
        google_client_secret=client_secret,
        session_secret=session_secret,
        base_url=base_url.rstrip("/"),
        api_token=env.get("SONAR_API_TOKEN") or None,
    )
