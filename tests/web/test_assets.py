"""Content versions for static assets (SPEC §13)."""

import hashlib

import pytest
from fastapi.testclient import TestClient

from sonar.web.app import STATIC_DIR, create_app
from sonar.web.assets import content_version, static_url_builder
from tests.html import soup


def test_content_version_uses_first_ten_sha256_hex_digits():
    assert content_version(b"abc") == hashlib.sha256(b"abc").hexdigest()[:10]


def test_builder_versions_files_once_and_skips_source(tmp_path):
    asset = tmp_path / "a.css"
    asset.write_bytes(b"original")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "script.js").write_bytes(b"script")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "input.css").write_bytes(b"source")

    static_url = static_url_builder(tmp_path)
    asset.unlink()

    assert static_url("a.css") == f"/static/a.css?v={content_version(b'original')}"
    assert static_url("vendor/script.js") == (
        f"/static/vendor/script.js?v={content_version(b'script')}"
    )
    with pytest.raises(KeyError):
        static_url("missing.css")
    with pytest.raises(KeyError):
        static_url("src/input.css")


def test_index_versions_its_stylesheet_and_htmx_script(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "test.db")) as client:
        response = client.get("/")
    assert response.status_code == 200
    page = soup(response)
    version = content_version((STATIC_DIR / "sonar.css").read_bytes())
    assert page.select_one('link[rel="stylesheet"]')["href"] == f"/static/sonar.css?v={version}"
    names = ["vendor/htmx.min.js"]
    sources = [script.get("src") for script in page.select("script[src]")]
    for name in names:
        version = content_version((STATIC_DIR / name).read_bytes())
        assert f"/static/{name}?v={version}" in sources
