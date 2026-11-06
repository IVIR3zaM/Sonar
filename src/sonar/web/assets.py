"""Static asset content versions computed once at startup."""

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path


def content_version(data: bytes) -> str:
    return sha256(data).hexdigest()[:10]


def static_url_builder(static_dir: Path) -> Callable[[str], str]:
    urls = {
        path.relative_to(static_dir).as_posix(): (
            f"/static/{path.relative_to(static_dir).as_posix()}"
            f"?v={content_version(path.read_bytes())}"
        )
        for path in static_dir.rglob("*")
        if path.is_file() and path.relative_to(static_dir).parts[0] != "src"
    }
    return urls.__getitem__
