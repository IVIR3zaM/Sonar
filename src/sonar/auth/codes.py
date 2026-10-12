"""In-memory one-time sign-in codes (SPEC §13 Sign-in).

Pure: the caller passes `now` (timezone-aware) and the client key; nothing here reads the clock.
Only HMAC digests are kept, so a memory dump never shows a usable code.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

CODE_TTL = timedelta(minutes=5)
ATTEMPT_WINDOW = timedelta(minutes=15)
MAX_ATTEMPTS_PER_CLIENT = 5
MAX_FAILURES = 5
_CODE_FORMAT = re.compile(r"[0-9]{6}")


class TooManyAttempts(Exception):
    """The client already used its redeem attempts in the current window."""


class SignInCodes:
    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)
        self._pending: dict[str, tuple[bytes, datetime]] = {}  # email -> (digest, issued_at)
        self._attempts: dict[str, list[datetime]] = {}  # client -> attempt times in the window
        self._failures = 0

    def issue(self, email: str, now: datetime) -> str:
        """Create a code for `email`, replacing any pending one."""
        self._prune(now)
        code = f"{secrets.randbelow(10**6):06d}"
        self._pending[email] = (self._digest(code), now)
        return code

    def redeem(self, code: str, client: str, now: datetime) -> str | None:
        """Return the code's email or None; raise TooManyAttempts when `client` is limited."""
        self._prune(now)
        attempts = self._attempts.setdefault(client, [])
        if len(attempts) >= MAX_ATTEMPTS_PER_CLIENT:
            raise TooManyAttempts(client)
        attempts.append(now)

        email = self._take(code.strip())
        if email is None:
            self._record_failure()
        return email

    def _take(self, code: str) -> str | None:
        if not _CODE_FORMAT.fullmatch(code):
            return None
        digest = self._digest(code)
        for email, (stored, _issued_at) in self._pending.items():
            if hmac.compare_digest(stored, digest):
                del self._pending[email]
                return email
        return None

    def _record_failure(self) -> None:
        self._failures += 1
        if self._failures >= MAX_FAILURES:
            self._pending.clear()
            self._failures = 0

    def _digest(self, code: str) -> bytes:
        return hmac.new(self._key, code.encode("ascii"), hashlib.sha256).digest()

    def _prune(self, now: datetime) -> None:
        self._pending = {
            email: entry for email, entry in self._pending.items() if now < entry[1] + CODE_TTL
        }
        fresh = {
            client: [at for at in times if now < at + ATTEMPT_WINDOW]
            for client, times in self._attempts.items()
        }
        self._attempts = {client: times for client, times in fresh.items() if times}
