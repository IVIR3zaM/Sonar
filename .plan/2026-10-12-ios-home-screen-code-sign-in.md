# iOS home-screen sign-in code
status: RUNNING
created: 2026-10-12 · updated: 2026-10-12
goal: The iPhone home-screen Sonar app gets its own 14-day session by typing a one-time 6-digit code that the Google sign-in panel shows, while normal browsers keep the direct redirect.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: On iOS the home-screen (standalone) app opens Google sign-in in an in-app Safari panel whose cookies the app never sees, so the panel ends up signed in and the app stays signed out on every launch. The app should instead start a "code" sign-in: once Google confirms a verified, allow-listed email, the panel shows a short one-time code, the owner closes the panel and types the code into the app's login page, and the app gets the same 14-day rolling session a browser sign-in gives.

In scope: an in-memory one-time code store in `src/sonar/auth/codes.py`; a code mode on `/auth/google` and `/auth/callback` with a bare code page; an always-visible "Have a sign-in code?" form on the login page and a `POST /auth/code` exchange in `src/sonar/web/pages/auth.py`; a small static `sign_in.js` that switches the Google button to code mode only in standalone display; an injectable clock on `create_app`; tests first for all of it; a SPEC §13 bullet; the rebuilt `sonar.css`.

Out of scope: automatic handoff without typing, Google Identity Services or popups, a web app manifest, session length, API token behaviour, any DB table or migration, and the normal browser callback (it keeps redirecting to /).

Constraints: AGENTS.md rules: strict TDD, KISS, pure auth logic without sqlite or web imports (`tests/test_architecture.py`), routes only in `web/pages/auth.py`, page tests on ids through `tests/html.py`, no inline `<style>` or new inline script, `sonar.css` rebuilt and committed, ruff clean. Security: CSPRNG codes stored only as keyed hashes, single use, 5-minute TTL, re-checked against the access list, per-IP limit plus mass invalidation, one generic error, Origin-checked POST, codes never in URLs, redirects or logs. Decisions D1-D14.

Definition of done: tests cover issue, exchange, expiry, single use, the rate limit, invalidation, the generic error, the Origin check and code mode against the normal callback; SPEC §13 has the code-flow bullet; the visual gate passes on the login and code pages at desktop and 375px, light and dark; the owner confirms on the iPhone home-screen app that the typed code lands on the dashboard and the next launch stays signed in; the final check passes verify and SPEC §11 and §12.

## Decisions

- D1 Trigger: in standalone display (`navigator.standalone === true` or `matchMedia("(display-mode: standalone)").matches`) `static/sign_in.js` rewrites `#google-sign-in` href to `/auth/google?mode=code`; `/auth/google` sets `session["code_mode"] = True` only for `mode=code` and removes it otherwise; the callback reads it before `session.clear()` | confirmed
- D2 Code-mode callback: after the existing `email_verified` check, check the access list; listed → issue a code and render bare `sign_in_code.html` (200, `Cache-Control: no-store`), the panel session keeps no email; unverified or unlisted → the existing not-allowed page, no code. The normal callback is unchanged | confirmed
- D3 Store: `src/sonar/auth/codes.py`, one in-memory instance per `create_app`; code `f"{secrets.randbelow(10**6):06d}"`; kept only as HMAC-SHA256 under a per-instance `secrets.token_bytes(32)` key; valid while `now < issued_at + 5 min`; single use; one pending code per email (a new one replaces the old); expired entries pruned on every call; a restart loses pending codes | confirmed
- D4 Limits: at most 5 exchange attempts per client IP in a sliding 15 minutes (every attempt counts, success included); the 6th answers 429 without looking at the code; separately every 5th rejected attempt from any IP drops all pending codes. The IP is `request.client.host`, which uvicorn already resolves from the local proxy (`src/sonar/__main__.py:63-66`); the app never reads X-Forwarded-For itself. Anyone can void a pending code by guessing 5 times; the owner then signs in again | confirmed
- D5 Exchange: `POST /auth/code`, form field `code`, trimmed, exactly 6 ASCII digits. Success → `session.clear()`, `session["email"] = email`, 303 to `/` (same SessionMiddleware cookie, 14-day rolling `max_age`). Wrong, malformed, expired, used, or the email no longer listed → login page 400 with the one inline error "That code did not work. Sign in with Google again to get a new one." on the code field (SPEC §12 inline error, entered value kept) | confirmed
- D6 CSRF: the POST needs `Origin` equal to the origin of `SONAR_BASE_URL`, or, without Origin, a `Referer` starting with base_url + `/`; otherwise 403 login page with the generic error, counted as no attempt. SameSite=Lax stays | confirmed
- D7 Clock: `create_app` gains `now: Callable[[], datetime]` (default timezone-aware UTC now), passed to the auth router; `codes.py` methods take `now: datetime` and never read the clock | confirmed
- D8 Login form: under the Google button, always shown (works without JS): `<form id="code-sign-in" method="post" action="/auth/code">`, the `field` macro with name `code`, label "Have a sign-in code?", `inputmode="numeric"`, `autocomplete="one-time-code"`, `pattern="[0-9]{6}"`, `maxlength="6"`, required; button "Sign in with code" | confirmed
- D9 Code page text: the code in `#sign-in-code` (six digits, large, tabular), "Tap ✕ and type this code in Sonar.", "It works once, within 5 minutes." | confirmed
- D10 Logging: no app logging is added (the app has none); uvicorn's access log already records method, path, status and IP of every attempt, and the code travels only in the POST body and the code page | confirmed
- D11 SPEC: one new §13 bullet "Sign-in code (§13 Sign-in)" after SPEC.md:245 describing D1-D6; no other SPEC line changes | confirmed
- D12 Order: the owner iPhone gate (N06) comes before the whole-plan check (N07), since a plan's last node is that check | confirmed
- D13 Visual gate setup (pre-authorized): a scratch launcher in the session scratchpad (never in the repo) runs `create_app` on a temp DB with sign-in settings for `http://127.0.0.1:8000` and a stand-in Google that redirects straight to `/auth/callback` and returns a verified `owner@example.com`, allowed with `uv run sonar allow-email owner@example.com --db <tmp db>` | confirmed
- D14 The owner deploys to the server themselves at N06; the plan never pushes or deploys (`push: none`) | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | sign-in code store | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | code-mode callback and code page | exec | N02 | sonnet/sonnet | 0 | 0 | TODO | |
| N04 | code exchange form and standalone script | exec | N03 | sonnet/opus | 0 | 0 | TODO | |
| N05 | visual check | gate | N04 | -/- | 0 | 0 | TODO | |
| N06 | owner iPhone check | gate | N05 | -/- | 0 | 0 | TODO | |
| N07 | plan acceptance | check | N06 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point before any work: verify passes on the untouched tree, the auth and form
  dependencies import, the Tailwind CLI builds (it is the only download), and the repo is writable. Tests never
  reach Google, so no other network endpoint is needed.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `uv run python -c "import authlib, itsdangerous, python_multipart, bs4"` exits 0
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C4 [cmd] `test -w .git/index && git status --porcelain >/dev/null` exits 0

## N02 sign-in code store
Do: Add `src/sonar/auth/codes.py` with an in-memory `SignInCodes`: `issue(email, now) -> str` returns a new
  6-digit code; `redeem(code, client, now) -> str | None` returns the email for a valid code and None for any
  rejection, and raises `TooManyAttempts` when `client` is over its limit. Plain Python: no sqlite, no web
  imports, no logging, never reads the clock.
Context: D3 code `f"{secrets.randbelow(10**6):06d}"`, stored only as HMAC-SHA256 under a per-instance
  `secrets.token_bytes(32)` key (no plaintext kept); valid while `now < issued_at + 5 min`; single use; one
  pending code per email, a new issue replaces it; expired entries pruned on every call. D4 every redeem from a
  client counts; with 5 attempts already in the last 15 minutes the next raises without checking or counting;
  each rejected redeem bumps a store-wide failure counter and the 5th drops all pending codes and resets it;
  attempt timestamps older than 15 minutes are pruned. D5 a code that is not exactly 6 ASCII digits after
  trimming is a rejection. D7 `now` is a timezone-aware datetime passed in. Style: `src/sonar/auth/emails.py`.
Read: `src/sonar/auth/emails.py`, `tests/auth/test_emails.py`, `tests/test_architecture.py`
Write: `src/sonar/auth/codes.py`, `tests/auth/test_codes.py`
Test first: a code issued for owner@example.com at 10:00 and redeemed at 10:04 from 203.0.113.5 gives
  owner@example.com; the module does not exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/auth/test_codes.py` passes tests for: success inside the TTL; rejected at
  exactly issued+5 min and later; a second redeem of the same code rejected; a wrong code rejected; "12345",
  "12a456" and "" rejected; a second issue for the same email voids the first; every code matches `^\d{6}$`
- C2 [cmd] `uv run pytest -q tests/auth/test_codes.py -k "limit or invalidat"` passes tests: the 6th attempt
  from one client inside 15 minutes raises TooManyAttempts even with a valid code; the same client succeeds
  once 15 minutes passed; another client is not limited; after 5 rejected attempts spread over clients a code
  issued before them is rejected
- C3 [review] `codes.py` holds only digests (no attribute or dict key holds the plaintext code), uses `secrets`
  for codes and key and `hmac` for digests, has no `datetime.now`/`date.today`/`time.time`, no print or
  logging, and prunes expired codes and stale attempts so memory stays bounded
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 code-mode callback and code page
Do: Let a code-mode Google round trip end on a code page instead of a session. `/auth/google` records the mode
  in the session; the callback in code mode checks the access list, issues a code and renders the new bare
  `sign_in_code.html`. `create_app` gains the injected clock and builds one `SignInCodes` per app, passed with
  `db_path` and `now` to `auth_pages.build_router`. Rebuild `sonar.css`.
Context: D1 `mode=code` sets `session["code_mode"] = True` before `google.authorize_redirect`
  (src/sonar/web/pages/auth.py:49-51); any other value or none removes it; read it before `session.clear()`
  (auth.py:64). D2 after the `email_verified` check (auth.py:65-66) a code-mode callback checks the access
  list (`access._is_allowed`, src/sonar/web/access.py:81-83; make it public if reused); unlisted → 
  `not_allowed_page`; listed → `codes.issue(email, now())`, 200 with `Cache-Control: no-store`, no email in
  the session; the normal path (auth.py:67-69) is unchanged. D7 `create_app(..., now=...)`
  (src/sonar/web/app.py:82-87,124-126), default aware UTC now. D9 template: extends base.html, `bare`, `card`
  macro like login.html, the code in `#sign-in-code`, text "Tap ✕ and type this code in Sonar." and "It works
  once, within 5 minutes."; no inline style or script. Fake Google: tests/web/fake_google.py; reuse the helpers
  of tests/web/test_auth_pages.py:24-75 (import them or move them into fake_google.py).
Read: `src/sonar/web/pages/auth.py`, `src/sonar/web/access.py`, `src/sonar/web/app.py:82-138`, `src/sonar/web/templates/login.html`, `src/sonar/web/templates/components/card.html`, `src/sonar/auth/codes.py`, `tests/web/test_auth_pages.py`, `tests/web/fake_google.py`, `tests/html.py`
Write: `src/sonar/web/pages/auth.py`, `src/sonar/web/access.py`, `src/sonar/web/app.py`, `src/sonar/web/templates/sign_in_code.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_auth_codes.py`, `tests/web/test_auth_pages.py`, `tests/web/fake_google.py`
Test first: `/auth/google?mode=code` then the callback for a listed verified email answers 200 with a
  six-digit `#sign-in-code`; today it redirects to /, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_auth_codes.py -k code_mode` passes: the code-mode callback answers
  200 with `#sign-in-code` text matching `^\d{6}$`, `Cache-Control: no-store`, no `location` header, and the
  same client's GET / still redirects to /auth/login
- C2 [cmd] `uv run pytest -q tests/web/test_auth_codes.py -k "normal or unlisted or unverified"` passes:
  `/auth/google` without mode, also right after an earlier `?mode=code` in the same client, still gives a 302
  to `/`; code mode with an unlisted or unverified email gives the 403 not-allowed page and no `#sign-in-code`
- C3 [review] pages/auth.py reads time only through the injected `now`; sign_in_code.html extends base.html,
  is bare, uses the card macro, has no `<style>` or `<script>`; sonar.css is rebuilt
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 code exchange form and standalone script
Do: Add the always-visible code form to the login page and `POST /auth/code`, which turns a valid code into a
  session in the browser that posts it. Add `src/sonar/web/static/sign_in.js`, which switches the Google button
  to code mode only in standalone display, loaded with `<script src="/static/sign_in.js" defer>` like
  src/sonar/web/templates/payoff.html:94. Add the SPEC §13 bullet. Rebuild `sonar.css`.
Context: D4 client = `request.client.host`; `TooManyAttempts` → 429. D5 field `code`; success →
  `session.clear()`, `session["email"]`, 303 to `/`; wrong, malformed, expired, used or no longer listed → 400
  login page with the inline field error "That code did not work. Sign in with Google again to get a new one."
  (entered value kept). D6 Origin must equal the base_url origin (`AuthSettings.base_url`,
  src/sonar/auth/settings.py:24), else a Referer starting with base_url + "/"; otherwise 403 with the same
  error, before `redeem`, so it costs no attempt. D8 form `#code-sign-in` method post action `/auth/code`
  under `#google-sign-in` (login.html:12), `field` macro (components/field.html:11) with label "Have a sign-in
  code?", attrs inputmode numeric, autocomplete one-time-code, pattern `[0-9]{6}`, maxlength 6, required;
  button "Sign in with code". D1 the script changes the href only when `navigator.standalone === true` or
  `matchMedia("(display-mode: standalone)").matches`. D11 one §13 bullet after SPEC.md:245. Tests base_url is
  http://testserver (tests/web/test_auth_pages.py:24-29); a second TestClient plays the home-screen app.
Read: `src/sonar/web/pages/auth.py`, `src/sonar/web/templates/login.html`, `src/sonar/web/templates/components/field.html`, `src/sonar/web/templates/components/button.html`, `src/sonar/auth/codes.py`, `tests/web/test_auth_codes.py`, `tests/web/test_static.py:50-60`, `SPEC.md:240-247`
Write: `src/sonar/web/pages/auth.py`, `src/sonar/web/templates/login.html`, `src/sonar/web/static/sign_in.js`, `src/sonar/web/static/sonar.css`, `SPEC.md`, `tests/web/test_auth_codes.py`, `tests/web/test_auth_pages.py`, `tests/web/test_static.py`
Test first: a code from the code-mode callback POSTed by a second client with Origin http://testserver gets
  303 to `/`; the route does not exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_auth_codes.py -k exchange` passes: the second client gets 303 to
  `/`, then GET / and GET /api/categories answer 200; its session cookie has Max-Age 1209600 and holds only email
- C2 [cmd] `uv run pytest -q tests/web/test_auth_codes.py -k "wrong or expired or reused or revoked"` passes: a
  wrong code, a code posted with the clock 5 minutes on, a used code and a code whose email was revoked first
  each give 400 with identical `#field-code-error` text and no signed-in session
- C3 [cmd] `uv run pytest -q tests/web/test_auth_codes.py -k "limit or origin"` passes: the 6th POST from one
  client in 15 minutes gives 429 even with a valid code; 5 wrong codes void a pending valid code; a foreign
  Origin, or neither Origin nor Referer, gives 403 and a valid code still works afterwards; GET /auth/code is 405
- C4 [cmd] `uv run pytest -q tests/web -k "login_page or sign_in_js"` passes: `#code-sign-in` posts to
  /auth/code with input `code` (inputmode numeric, autocomplete one-time-code); `#google-sign-in` href stays
  /auth/google; `script[src="/static/sign_in.js"]` is on the page; GET /static/sign_in.js is 200
- C5 [review] sign_in.js changes only the href and only under the D1 condition; no inline script in
  login.html; no code in any redirect, URL, log or print; SPEC.md gains one §13 bullet matching D1-D6 and
  nothing else; sonar.css is rebuilt
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 visual check
Do: gate, pre-authorized (D13). Start a scratch launcher (session scratchpad, never the repo) that runs `create_app` on a
  temp DB with `AuthSettings` (dummy client id and secret, a random 32+ character session secret, base_url
  http://127.0.0.1:8000) and a stand-in Google whose `authorize_redirect` stores a state key in the session and
  redirects to /auth/callback, and whose `authorize_access_token` returns a verified owner@example.com; serve
  it on 127.0.0.1:8000 and run `uv run sonar allow-email owner@example.com --db <tmp db>`. Open /auth/login,
  submit a wrong code, then open /auth/google?mode=code, read the code and type it into the login form. Check
  the login page (plain and with the error) and the code page at desktop and 375px, light and dark
  (read_page first; scaled screenshots only where layout matters).
Done when:
- C1 [visual] /auth/login shows the Google button and under it "Have a sign-in code?" with a code field and a
  "Sign in with code" button inside the card, no overflow at 375px
- C2 [visual] a wrong code shows the inline error under the code field, legible in light and dark
- C3 [visual] /auth/google?mode=code shows the code page with six large legible digits and "Tap ✕ and type
  this code in Sonar.", no navigation, in all four views
- C4 [visual] typing that code into /auth/login lands on the dashboard signed in as owner@example.com

## N06 owner iPhone check
Do: gate for the owner (D14): the owner deploys the committed tree to the server themselves, then on the iPhone home-screen
  Sonar app taps Sign in with Google, finishes Google in the panel, reads the code, taps ✕, types the code,
  then closes and relaunches the app; finally signs in once from plain Safari.
Done when:
- C1 [human] after typing the code the home-screen app shows the dashboard, with no Safari chrome
- C2 [human] relaunching the home-screen app opens signed in, without the login page
- C3 [human] sign-in from plain Safari goes straight to the dashboard, with no code page

## N07 plan acceptance
Do: Whole-plan check: the full verify, the CSS against a fresh build, SPEC §11 (SPEC.md:162) and §12
  (SPEC.md:178) for the two changed pages, and the security Decisions D3-D6 in the code.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [review] SPEC §11 and §12 hold for login.html and sign_in_code.html: extend base.html, compose the
  component macros, no inline `<style>`, form errors inline with status 400 keeping the entered value
- C4 [review] D3-D6 hold in src/sonar/auth/codes.py and src/sonar/web/pages/auth.py: CSPRNG codes, keyed-hash
  storage only, single use, 5-minute TTL, access list re-checked at exchange, per-IP limit, invalidation after
  5 rejections, one generic error, Origin/Referer check, no code in a URL, redirect or log
- C5 [review] the SPEC §13 bullet matches the behaviour; no migration was added; the normal callback, session
  length and API token handling are unchanged (tests/web/test_auth_pages.py, tests/web/test_auth_api_token.py)

## Log

### N01 try 1 · 2026-10-12
check: PASS 4/4

### N02 try 1 · 2026-10-12
exec: DONE · 1367 passed
- Added SignInCodes and TooManyAttempts in auth/codes.py with HMAC digests, TTL, per-client and store-wide limits
- Successful and malformed redeems both count as attempts; malformed counts as a failure
check: PASS 3/3
verify: PASS
