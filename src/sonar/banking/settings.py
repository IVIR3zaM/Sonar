"""Bank sync settings (SPEC §13 Bank sync): on only when the app id and key path are both set.

Pure: the caller passes the environment, so only `__main__` ever reads `os.environ`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key

BANK_ENV_VARS = ("SONAR_ENABLE_BANKING_APP_ID", "SONAR_ENABLE_BANKING_KEY_PATH")
ASPSP_NAME = "Deutsche Bank"
ASPSP_COUNTRY = "DE"
_DEFAULT_PORT = "8000"


@dataclass(frozen=True)
class BankSettings:
    app_id: str
    key_path: Path
    redirect_url: str


def bank_settings(env: Mapping[str, str]) -> BankSettings | None:
    """The bank sync settings in `env`; None when neither variable is set.

    An empty value counts as unset. Setting only one raises ValueError naming the other:
    half-configured bank sync must never silently mean "no bank sync".
    """
    app_id, key_path = (env.get(name, "") for name in BANK_ENV_VARS)
    missing = [name for name in BANK_ENV_VARS if not env.get(name, "")]
    if len(missing) == len(BANK_ENV_VARS):
        return None
    if missing:
        raise ValueError(f"Bank sync is only partly configured; missing: {', '.join(missing)}")
    return BankSettings(app_id=app_id, key_path=Path(key_path), redirect_url=_redirect_url(env))


def _redirect_url(env: Mapping[str, str]) -> str:
    base_url = env.get("SONAR_BASE_URL", "").rstrip("/")
    if not base_url:
        base_url = f"http://127.0.0.1:{env.get('SONAR_PORT') or _DEFAULT_PORT}"
    return f"{base_url}/bank/callback"


def read_private_key(path: Path, served_dir: Path) -> bytes:
    """The key file's bytes, after checking it is safe to sign with.

    Errors name the path, never the contents. A key inside `served_dir` would be
    downloadable, so it is refused, symlinks included.
    """
    if path.resolve().is_relative_to(served_dir.resolve()):
        raise ValueError(f"Enable Banking key {path} lies inside the served static files")
    try:
        data = path.read_bytes()
    except OSError:
        raise ValueError(f"Enable Banking key {path} cannot be read") from None
    try:
        load_pem_private_key(data, None)
    except (ValueError, TypeError):
        raise ValueError(
            f"Enable Banking key {path} is not an unencrypted PEM private key"
        ) from None
    return data
