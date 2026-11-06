# Static asset cache busting
status: DONE
created: 2026-11-06 · updated: 2026-11-06
goal: every page links its static files with a content-hash version, so a deploy is never served stale CSS or JS
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: After a deploy, browsers and the Cloudflare edge fetch the new stylesheet and scripts at once, because every
static URL a page emits changes whenever that file's content changes; unchanged files keep their cached copy.

In scope: a small helper in the web layer that hashes static files once at startup and turns a static path into
`/static/<path>?v=<hash>`; a Jinja global `static_url` wired in `app.py`; every `/static/` link and script in
`base.html` plus the payoff script in `payoff.html` going through it; the page tests that pinned exact hrefs; a
SPEC §13 bullet.

Out of scope: Cloudflare configuration, cache headers on `/static`, the icon URL inside `manifest.webmanifest`,
any visual change, and every other behavior.

Constraints: AGENTS.md rules: strict TDD, KISS, `app.py` wires only and has no routes (`tests/test_architecture.py`),
page tests assert on hooks through `tests/html.py`; no template looks different, so no gate node.

Definition of done: verify passes and `GET /` renders `<link rel="stylesheet" href="/static/sonar.css?v=<hash>">`
where the hash is the first 10 hex characters of the SHA-256 of `src/sonar/web/static/sonar.css`.

## Decisions

- D1 Cloudflare's default cache key includes the query string, so a new `?v=` value is a cache miss and the old URL can stay cached. | confirmed
- D2 Version = first 10 hex characters of the SHA-256 of the file's bytes, read once when `app.py` is imported (startup), not per request; a CSS rebuild in dev needs an app restart. | confirmed
- D3 Pure part `content_version(data: bytes) -> str` and the startup reader `static_url_builder(static_dir)` live in a new `src/sonar/web/assets.py` beside `display.py`; `app.py` only registers `templates.env.globals["static_url"]`. | confirmed
- D4 Every `/static/` reference in `base.html` (lines 51-53, 65, 66) and `payoff.html:94` uses `static_url`; the manifest's own icon `src` stays a plain path. | confirmed
- D5 `static_url` with a name that is not a file under the static dir raises, so a typo fails the page test instead of rendering an unversioned URL. | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | hashed static urls | exec | - | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |

## N01 hashed static urls
Do: Add `src/sonar/web/assets.py` with pure `content_version(data: bytes) -> str` (first 10 hex of SHA-256) and
  `static_url_builder(static_dir: Path) -> Callable[[str], str]` that hashes every file under `static_dir` (skip
  `src/`) once when it is called; the returned `static_url("sonar.css")` gives `/static/sonar.css?v=<version>`, and
  an unknown name raises `KeyError`. In
  `src/sonar/web/app.py` next to the filters (app.py:76-87) register `templates.env.globals["static_url"] =
  static_url_builder(STATIC_DIR)` (STATIC_DIR at app.py:48). Route every `/static/` href and src in
  `src/sonar/web/templates/base.html` (lines 51, 52, 53, 65, 66) and `payoff.html:94` through `static_url(...)`.
  Update the tests that pin exact hrefs. Append a §13 bullet to `SPEC.md` after line 278: "Static asset versions
  (§12): every static link and script carries `?v=` + the first 10 hex of the file's SHA-256, computed at
  startup, so a deploy busts the browser and CDN caches; the manifest's icon path stays plain."
Context: D2 hash once at startup, not per request. D3 helper in `web/assets.py`, `app.py` wires only and must keep
  no route decorators (`tests/test_architecture.py:100-110`). D4 manifest icon `src`
  (`static/manifest.webmanifest:9`) unchanged. D5 unknown name raises. Exact-href asserts to update to the
  versioned URL (compute the expected value with `content_version` on the file's bytes, never a literal):
  `tests/web/test_static.py:44-45`, `:66`, `tests/web/test_auth_pages.py:294`. No visual change: do not rebuild or
  touch `sonar.css`.
Read: `src/sonar/web/app.py`, `src/sonar/web/templates/base.html`, `src/sonar/web/templates/payoff.html`, `tests/web/test_static.py`, `tests/web/test_auth_pages.py`, `tests/html.py`
Write: `src/sonar/web/assets.py`, `src/sonar/web/app.py`, `src/sonar/web/templates/base.html`, `src/sonar/web/templates/payoff.html`, `tests/web/test_assets.py`, `tests/web/test_static.py`, `tests/web/test_auth_pages.py`, `tests/web/test_payoff_page.py`, `SPEC.md`
Test first: `tests/web/test_assets.py`: `content_version(b"abc")` equals `hashlib.sha256(b"abc").hexdigest()[:10]`;
  the builder on a tmp dir maps `a.css` to `/static/a.css?v=<version>` and raises `KeyError` for a missing name;
  `GET /` has `link[rel="stylesheet"]` with href `/static/sonar.css?v=` + `content_version` of the real file
  (via `tests.html.soup`), and the htmx script src carries its own version.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_assets.py tests/web/test_static.py tests/web/test_auth_pages.py tests/web/test_payoff_page.py tests/test_architecture.py`
- C2 [cmd] `sh -c '! grep -nE "(href|src)=\"/static/" src/sonar/web/templates/*.html src/sonar/web/templates/components/*.html'`
- C3 [review] `src/sonar/web/assets.py` holds the hashing; `app.py` adds only the one `static_url` global line
  (plus its import); files are hashed once when the builder is built, not per render; `payoff.html` script and
  all five `base.html` references use `static_url`; `manifest.webmanifest` and `sonar.css` are unchanged; the
  SPEC §13 bullet is appended after the last line.
- C4 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-11-06
exec: DONE · 2243 passed; ruff check and format clean; static-reference check clean
- Added startup SHA-256 static URL mapping, versioned six template references, and appended SPEC §13.
- Tests cover digest, nested files, missing names, skipped src, startup snapshot, and versioned page assets; manifest icon and sonar.css unchanged.
check: PASS 3/3
verify: PASS
