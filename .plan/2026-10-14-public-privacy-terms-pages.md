# Public privacy and terms pages
status: DONE
created: 2026-10-14 · updated: 2026-10-14
goal: /privacy and /terms are static pages anyone can open without signing in, while every other route stays behind the sign-in gate.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: The Enable Banking application form needs a privacy policy URL and a terms URL that answer for anyone. Sonar gets two static pages, /privacy and /terms, that open without a Google session and say plainly that Sonar is a private household tool that keeps the owner's bank data in the owner's own database.

In scope: one page router `src/sonar/web/pages/legal.py` with the two GET routes, two bare templates extending `base.html`, an exact-path exemption for exactly these two paths in the sign-in gate (`src/sonar/web/access.py:25,37`), the router registered in `src/sonar/web/app.py`, tests written first (the two pages are public, every other route is still gated, lookalike paths are still gated, sign-in off is unchanged), one SPEC §13 bullet, and the rebuilt `sonar.css`.

Out of scope: links to the pages from the app or links out of them, any data on the pages, auth of any other route, deploying or registering the URLs at Enable Banking, and the paused plan enable-banking-daily-sync.

Constraints: AGENTS.md rules: strict TDD, page routes only in `web/pages/`, pages extend `base.html` with no inline `<style>`, page tests on ids through `tests/html.py`, `sonar.css` rebuilt and committed, ruff check and format clean, a visual gate at desktop and 375px, light and dark. The sign-in gate must not get weaker for any path except these two. No personal names, emails or addresses in tracked files. Decisions D1-D7.

Definition of done: with sign-in on and no session, GET /privacy and /terms answer 200 with the agreed text; every other route still redirects to /auth/login (pages) or answers 401 (API); lookalike paths stay gated; with sign-in off the app has no session middleware and no auth routes, as before; the full verify is clean; the app starts with one command; the gate sees both pages in all four views.

## Decisions

- D1 Exemption by exact path: a new `PUBLIC_PATHS = frozenset({"/privacy", "/terms"})` next to `PUBLIC_PREFIXES` (src/sonar/web/access.py:25), checked with `path in PUBLIC_PATHS`; `/privacy/`, `/privacy/x`, `/privacyx` and `/terms.html` stay gated | confirmed: exact match
- D2 The router `src/sonar/web/pages/legal.py` (`build_router(templates)`) is registered always, sign-in on or off, GET only, reading no DB, query or session | confirmed: always registered
- D3 Both pages are bare (`{% set bare = true %}` as in login.html:4): no nav, no badge hx-get, no bank banner, for signed-in visitors too | confirmed: bare
- D4 Wording: card titles "Privacy policy" (id `privacy`) and "Terms of use" (id `terms`); privacy says Sonar is a self-hosted application for a private household, available only to its owner and listed household members; it reads the owner's own bank account data via Enable Banking and stores it only in the owner's own database; nothing is shared with, sold to or sent to any third party; the owner can delete the data at any time by deleting that database. Terms say Sonar is a personal tool for the private use of its owner and listed household members; it is not offered to the public and no service is provided to other users. No names, contact address or date | confirmed: as written
- D5 SPEC: a new last bullet in §13: "Public pages (§13 Sign-in): /privacy and /terms are static, bare pages with no data, served without sign-in in both modes; only these exact paths are exempt from the sign-in gate" | confirmed: new bullet
- D6 The plan pushes and deploys nothing (push: none) and registers nothing at Enable Banking; the URLs go live with the owner's next deploy | confirmed: owner deploys after the plan
- D7 The visual gate runs the config visual_recipe with sign-in off on a temp DB and skips the sample import and settings, since the pages read no data | confirmed: skip import

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | public privacy and terms pages | exec | - | sonnet/sonnet | 1 | 1 | DONE | |
| N02 | visual check | gate | N01 | -/- | 0 | 0 | DONE | |

## N01 public privacy and terms pages
Do: Add `src/sonar/web/pages/legal.py` with GET /privacy and /terms rendering `privacy.html` and `terms.html`
  (bare, `card` macro, the text below), register it in `create_app` for both modes, and exempt exactly these
  two paths in the sign-in gate. Add the SPEC bullet, update the access.py docstring, rebuild `sonar.css`.
Context: Gate: add `PUBLIC_PATHS = frozenset({"/privacy", "/terms"})` beside access.py:25 and
  `path in PUBLIC_PATHS` beside the prefix check at access.py:37; PUBLIC_PREFIXES unchanged. Router:
  `build_router(templates)`, included unconditionally near app.py:123-133, GET only, handlers take only
  `request`, no DB, query or session. Bare: `{% set bare = true %}` as login.html:4; base.html:143-151 then
  hides nav and bank banner, for signed-in visitors too. Card macro: components/card.html:6.
  privacy.html: card "Privacy policy", id `privacy`, saying: Sonar is a self-hosted application for a private
  household, available only to its owner and listed household members. It reads the owner's own bank account
  data via Enable Banking and stores it only in the owner's own database. Nothing is shared with, sold to or
  sent to any third party. The owner can delete the data at any time by deleting that database.
  terms.html: card "Terms of use", id `terms`, saying: Sonar is a personal tool for the private use of its
  owner and listed household members. It is not offered to the public and no service is provided to other
  users. No names, contact address or date on either page. SPEC.md: new last §13 bullet after SPEC.md:259,
  verbatim: "- Public pages (§13 Sign-in): /privacy and /terms are static, bare pages with no data, served
  without sign-in in both modes; only these exact paths are exempt from the sign-in gate". Tests: sign-in
  setup tests/web/test_auth_pages.py:24-36, bank on tests/web/test_bank_pages.py:23-45. CSS: AGENTS.md Setup.
Read: `src/sonar/web/access.py`, `src/sonar/web/app.py:85-145`, `src/sonar/web/pages/auth.py`, `src/sonar/web/templates/login.html`, `tests/web/test_auth_pages.py:1-112`, `tests/web/test_auth_off.py`, `tests/web/test_bank_pages.py:1-50`, `tests/html.py`
Write: `src/sonar/web/access.py`, `src/sonar/web/app.py`, `src/sonar/web/pages/legal.py`, `src/sonar/web/templates/privacy.html`, `src/sonar/web/templates/terms.html`, `tests/web/test_public_pages.py`, `tests/web/test_auth_off.py`, `SPEC.md`, `src/sonar/web/static/sonar.css`
Test first: in tests/web/test_public_pages.py, with sign-in on and no cookie, GET /privacy answers 200; today
  the gate answers 302 to /auth/login, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_public_pages.py -k "public"` passes: sign-in on, no cookie, GET
  /privacy and /terms answer 200 with `#privacy` / `#terms` holding the D4 sentences (third party, delete
  the database; not offered to the public), and with bank on the pages have no `nav`, no `[hx-get]` and no
  `#bank-banner-slot`
- C2 [cmd] `uv run pytest -q tests/web/test_public_pages.py -k "gated"` passes a sweep over every `APIRoute` of an
  app with sign-in and bank on (path params filled, each method), except `/auth/*`, /privacy and /terms: pages
  answer 302 to /auth/login, `/api` paths 401 JSON; the sweep includes `/`, `/settings`, `/api/rules`, `/bank/banner`
- C3 [cmd] `uv run pytest -q tests/web/test_public_pages.py -k "lookalike"` passes: `/privacy/`, `/privacy/x`,
  `/privacyx`, `/terms.html` and `/Terms` answer 302 to /auth/login when signed out
- C4 [cmd] `uv run pytest -q tests/web/test_auth_off.py` passes, including a new test that with sign-in off
  /privacy and /terms answer 200 while no SessionMiddleware and no /auth/login exist
- C5 [review] access.py adds only `PUBLIC_PATHS` and one exact membership check, PUBLIC_PREFIXES unchanged;
  legal.py has only the two GET handlers with no DB, query or session use; app.py only includes the router;
  templates extend base.html, set bare, use `card`, no `<style>`, no names or contacts; SPEC gains only the
  D5 bullet; sonar.css is rebuilt
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 visual check
Do: gate. The orchestrator starts the app per the config visual_recipe on a temp DB with sign-in off and,
  per D7, skips the sample import and settings. It opens http://127.0.0.1:8000/privacy and /terms at desktop
  and 375px, light and dark (read_page first; scaled screenshots only where layout matters).
Done when:
- C1 [visual] /privacy shows the Sonar brand and a "Privacy policy" card with the four D4 statements (private
  household, Enable Banking data in the owner's database, no third party, delete the database); no nav
- C2 [visual] /terms shows a "Terms of use" card saying it is for the owner and listed household members only
  and not offered to the public; no nav
- C3 [visual] in all four views the text wraps without widening the page at 375px and is legible in light and
  dark

## Log

### N01 try 1 · 2026-10-14
exec: BLOCKED · brief cites D4 (titles, ids, exact sentences of privacy/terms text) but its output does not include the Decisions; I may not open the plan

### N01 replan 1 · 2026-10-14
plan: REPLANNED
- cause: executor blocked, brief cited D4/D5 by reference and executors may not open the plan
- brief now states the D4 page titles, ids and every sentence, the D5 SPEC bullet verbatim and the D1/D2/D3 specifics inline; scope and criteria unchanged

### N01 try 1 · 2026-10-14
exec: DONE · 1448 passed
- legal.py router with /privacy and /terms (bare card pages), included in create_app; PUBLIC_PATHS exact-match exemption in the gate; SPEC bullet
- gated sweep reads paths from app.openapi() because this FastAPI nests routes in _IncludedRouter; sonar.css rebuilt, no diff
check: PASS 5/5
verify: PASS
