# iOS home-screen sign-in code
status: WAITING
created: 2026-10-12 · updated: 2026-10-12
goal: The iPhone home-screen Sonar app signs in with the plain Google flow and keeps its 14-day session across launches, the site scoped to the app by a web app manifest; the code sign-in is removed.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: On iOS the home-screen (standalone) app kept ending up signed out, because without a manifest its scope was the folder it was added from and the Google round trip left it. With a manifest whose scope is the whole site, the Google callback returns into the standalone app and sets the session in the app's own cookie jar, so the plain Google sign-in is enough: the owner taps Sign in with Google, finishes Google, lands on the dashboard inside the app, and stays signed in on the next launch for the usual 14-day rolling session.

In scope: the public `static/manifest.webmanifest` linked from `base.html` (done in N08); removing the whole code sign-in built earlier in this plan (the code store `src/sonar/auth/codes.py`, the code mode on `/auth/google` and `/auth/callback`, `sign_in_code.html`, the login page's code form, `POST /auth/code`, `static/sign_in.js`, the `now` clock on `create_app`, their tests); a regression test that a leftover `?mode=code` still signs in normally; the SPEC home-screen bullet cut down to the manifest; the rebuilt `sonar.css`.

Out of scope: one-time codes or any other handoff, Google Identity Services or popups, a service worker or offline mode, session length, API token behaviour, any DB table or migration, and changes to the normal Google flow itself.

Constraints: AGENTS.md rules: strict TDD, KISS, routes only in `web/pages/auth.py`, page tests on ids through `tests/html.py`, no inline `<style>` or script, `sonar.css` rebuilt and committed, ruff clean. After the removal the code under `src/` and `tests/` differs from the pre-plan tree (57a4928^) only by the manifest work and the regression test. Decisions D11-D16; D1-D10 are void by D16.

Definition of done: no code sign-in remains in `src/`, `tests/` or SPEC; every page links the manifest; the SPEC §13 home-screen bullet describes only the manifest; the login page passes the visual gate at desktop and 375px, light and dark; the owner re-adds the icon and confirms on the iPhone that plain Google sign-in lands on the dashboard inside the app and the next launch stays signed in; the final check passes verify and SPEC §11 and §12.

## Decisions

- D1 Trigger: in standalone display (`navigator.standalone === true` or `matchMedia("(display-mode: standalone)").matches`) `static/sign_in.js` rewrites `#google-sign-in` href to `/auth/google?mode=code`; `/auth/google` sets `session["code_mode"] = True` only for `mode=code` and removes it otherwise; the callback reads it before `session.clear()` | confirmed · void by D16
- D2 Code-mode callback: after the existing `email_verified` check, check the access list; listed → issue a code and render bare `sign_in_code.html` (200, `Cache-Control: no-store`), the panel session keeps no email; unverified or unlisted → the existing not-allowed page, no code. The normal callback is unchanged | confirmed · void by D16
- D3 Store: `src/sonar/auth/codes.py`, one in-memory instance per `create_app`; code `f"{secrets.randbelow(10**6):06d}"`; kept only as HMAC-SHA256 under a per-instance `secrets.token_bytes(32)` key; valid while `now < issued_at + 5 min`; single use; one pending code per email (a new one replaces the old); expired entries pruned on every call; a restart loses pending codes | confirmed · void by D16
- D4 Limits: at most 5 exchange attempts per client IP in a sliding 15 minutes (every attempt counts, success included); the 6th answers 429 without looking at the code; separately every 5th rejected attempt from any IP drops all pending codes. The IP is `request.client.host`, which uvicorn already resolves from the local proxy (`src/sonar/__main__.py:63-66`); the app never reads X-Forwarded-For itself. Anyone can void a pending code by guessing 5 times; the owner then signs in again | confirmed · void by D16
- D5 Exchange: `POST /auth/code`, form field `code`, trimmed, exactly 6 ASCII digits. Success → `session.clear()`, `session["email"] = email`, 303 to `/` (same SessionMiddleware cookie, 14-day rolling `max_age`). Wrong, malformed, expired, used, or the email no longer listed → login page 400 with the one inline error "That code did not work. Sign in with Google again to get a new one." on the code field (SPEC §12 inline error, entered value kept) | confirmed · void by D16
- D6 CSRF: the POST needs `Origin` equal to the origin of `SONAR_BASE_URL`, or, without Origin, a `Referer` starting with base_url + `/`; otherwise 403 login page with the generic error, counted as no attempt. SameSite=Lax stays | confirmed · void by D16
- D7 Clock: `create_app` gains `now: Callable[[], datetime]` (default timezone-aware UTC now), passed to the auth router; `codes.py` methods take `now: datetime` and never read the clock | confirmed · void by D16
- D8 Login form: under the Google button, always shown (works without JS): `<form id="code-sign-in" method="post" action="/auth/code">`, the `field` macro with name `code`, label "Have a sign-in code?", `inputmode="numeric"`, `autocomplete="one-time-code"`, `pattern="[0-9]{6}"`, `maxlength="6"`, required; button "Sign in with code" | confirmed · void by D16
- D9 Code page text: the code in `#sign-in-code` (six digits, large, tabular), "Tap ✕ and type this code in Sonar.", "It works once, within 5 minutes." | confirmed · void by D16
- D10 Logging: no app logging is added (the app has none); uvicorn's access log already records method, path, status and IP of every attempt, and the code travels only in the POST body and the code page | confirmed · void by D16
- D11 SPEC: the §13 code-flow bullet (SPEC.md:246) becomes one manifest-only bullet: every page links `static/manifest.webmanifest` with `scope` and `start_url` "/", so a home-screen app keeps the Google round trip and the redirect to `/` in its standalone window and signs in with the normal Google flow; no other SPEC line changes | confirmed
- D12 Order: the owner iPhone gate (N06) comes before the whole-plan check (N07), since a plan's last node is that check | confirmed
- D13 Visual gate setup (pre-authorized): a scratch launcher in the session scratchpad (never in the repo) runs `create_app` on a temp DB with sign-in settings for `http://127.0.0.1:8000` and a stand-in Google that redirects straight to `/auth/callback` and returns a verified `owner@example.com`, allowed with `uv run sonar allow-email owner@example.com --db <tmp db>` | confirmed
- D14 The owner deploys to the server themselves at N06; the plan never pushes or deploys (`push: none`) | confirmed
- D15 App scope: base.html (src/sonar/web/templates/base.html:6-23) links no manifest, so iOS scopes the home-screen app to the folder of the URL it was added from; added while signed out, that URL is /auth/login (the gate redirects there, src/sonar/web/access.py:51), so the scope is /auth/ and the 303 from `POST /auth/code` to `/` (src/sonar/web/pages/auth.py:133) leaves it and opens the in-app browser. Fix: serve a public `/static/manifest.webmanifest` (`name`/`short_name` "Sonar", `start_url` "/", `scope` "/", `display` "standalone", the apple-touch icon) and link it from base.html with `<link rel="manifest">`; this moves "a web app manifest" from Out of scope to In scope; the owner then deletes the home-screen icon and adds it again from Safari, as part of the N06 gate | confirmed
- D16 Code mode after the manifest: with scope "/" the Google callback came back into the standalone app (its own cookie jar; the state check passed, the code page rendered there with no ✕), so the plain Google flow should now set the session inside the home-screen app and code mode has no remaining use. Drop code mode: remove `static/sign_in.js` and its link, `mode=code` and the code-mode callback branch with `sign_in_code.html`, the login "Have a sign-in code?" form, `POST /auth/code`, `src/sonar/auth/codes.py`, the `now` clock on `create_app` and their tests (introduced by 57a4928, 42cfffb, 3978bad); keep the manifest (D15, b27a292); the SPEC.md:246 bullet shrinks to the manifest sentence; D1-D10 become void, the goal and Intent change to "home-screen app signs in with plain Google", N07 drops its code criteria; N06 then checks plain Google sign-in in the home-screen app and relaunch | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | sign-in code store | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | code-mode callback and code page | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | code exchange form and standalone script | exec | N03 | sonnet/opus | 1 | 0 | DONE | |
| N05 | visual check | gate | N04 | -/- | 0 | 0 | DONE | |
| N06 | owner iPhone check | gate | N10 | -/- | 0 | 2 | TODO | |
| N07 | plan acceptance | check | N06 | -/sonnet | 0 | 0 | TODO | |
| N08 | web app manifest | exec | N05 | haiku/sonnet | 1 | 0 | DONE | |
| N09 | drop code mode | exec | N08 | sonnet/sonnet | 2 | 0 | DONE | |
| N10 | login visual check | gate | N09 | -/- | 0 | 0 | DONE | |

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

## N08 web app manifest
Do: Give the home-screen app the whole site as its scope, so the 303 from `POST /auth/code` to `/` stays in the
  standalone app. Add a public static `manifest.webmanifest` and link it from base.html, so every page (the
  bare login page included) carries it. Extend the SPEC home-screen bullet with one sentence.
Context: D15 without a manifest iOS scopes the app to the folder it was added from (/auth/ via the gate
  redirect, src/sonar/web/access.py:51), and `/` leaves it. Manifest JSON: `name` and `short_name` "Sonar",
  `start_url` "/", `scope` "/", `display` "standalone", `icons` one entry `/static/icons/apple-touch-icon.png`,
  `sizes` "180x180", `type` "image/png". `/static/` is public under sign-in (access.py:25,37); StaticFiles
  (src/sonar/web/app.py:115) serves `.webmanifest` as `application/manifest+json`. Link
  `<link rel="manifest" href="/static/manifest.webmanifest">` next to the apple-touch-icon link
  (src/sonar/web/templates/base.html:50); no other template change. D11 the one SPEC change is a sentence
  appended to the home-screen bullet (SPEC.md:246) saying every page links a manifest with scope and start_url
  `/` so the post-code redirect stays in the app. Test pattern: tests/web/test_static.py:37-48; the sign-in
  app helpers are in tests/web/test_auth_pages.py:24-75. Rebuild `sonar.css` (no new classes, so no diff).
Read: `src/sonar/web/templates/base.html:44-64`, `tests/web/test_static.py`, `tests/web/test_auth_pages.py:1-80`, `SPEC.md:246`
Write: `src/sonar/web/static/manifest.webmanifest`, `src/sonar/web/templates/base.html`, `src/sonar/web/static/sonar.css`, `SPEC.md`, `tests/web/test_static.py`, `tests/web/test_auth_pages.py`
Test first: GET / links `rel="manifest" href="/static/manifest.webmanifest"` and GET of that file is 200 with
  scope "/"; no manifest exists yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_static.py -k manifest` passes: GET / has the manifest link; the file
  answers 200 with content-type `application/manifest+json` and JSON whose `scope` and `start_url` are "/",
  `display` "standalone", `name` "Sonar", and whose icon src answers 200
- C2 [cmd] `uv run pytest -q tests/web/test_auth_pages.py -k manifest` passes: with sign-in on and no session,
  GET /static/manifest.webmanifest is 200 and GET /auth/login carries the manifest link
- C3 [review] base.html gains only the one `<link rel="manifest">` line; the manifest has exactly the D15 keys;
  SPEC.md changes only by the one sentence on the home-screen bullet; sonar.css is rebuilt and unchanged
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N09 drop code mode
Do: Remove the whole code sign-in, now unused: since the manifest (scope "/") the Google callback returns into
  the home-screen app, so the plain Google flow signs it in. Delete the code store, code mode, code page, code
  form, `POST /auth/code`, `sign_in.js`, the `now` clock and their tests; keep the manifest. Cut the SPEC
  bullet down to the manifest. Rebuild `sonar.css`.
Context: D16 the target is the pre-plan tree `57a4928^` plus only N08's manifest work (b27a292) and this
  node's regression test; `git show 57a4928^:<path>` gives the before state of each file. Delete
  `src/sonar/auth/codes.py`, `tests/auth/test_codes.py`, `tests/web/test_auth_codes.py`,
  `src/sonar/web/templates/sign_in_code.html`, `src/sonar/web/static/sign_in.js`. In pages/auth.py drop
  `CODE_*`, `_code_page`, `_code_rejected`, `_from_this_site`, `_origin`, the `mode` param and branch
  (auth.py:88-95,107,112-113), `exchange_code` (auth.py:118-133), and `codes`/`db_path`/`now` from
  `build_router` (auth.py:45-52); the normal callback stays as is (302 to `/`). app.py: drop the `now`
  param, its docstring line, the `SignInCodes` import and argument (app.py:7,19,88,100,129-131). access.py:
  `is_allowed_email` back to private `_is_allowed` (access.py:52,81). login.html: drop the form and the
  script tag (login.html:14-18,21). Tests: drop test_auth_pages.py:273-300 and test_static.py:60-70; keep
  the manifest tests (test_static.py:72-100, test_auth_pages.py:302-310). D11 SPEC.md:246 becomes the
  manifest-only bullet "Home-screen app (§13 Sign-in)": every page links `static/manifest.webmanifest` with
  `scope` and `start_url` "/", so a home-screen app keeps the Google round trip and the redirect to `/` in
  its standalone window and signs in with the normal Google flow.
Read: `src/sonar/web/pages/auth.py`, `src/sonar/web/app.py:1-20,80-140`, `src/sonar/web/access.py:45-85`, `src/sonar/web/templates/login.html`, `tests/web/test_auth_pages.py`, `tests/web/test_static.py`, `SPEC.md:244-247`
Write: `src/sonar/auth/codes.py`, `tests/auth/test_codes.py`, `tests/web/test_auth_codes.py`, `src/sonar/web/templates/sign_in_code.html`, `src/sonar/web/static/sign_in.js`, `src/sonar/web/pages/auth.py`, `src/sonar/web/app.py`, `src/sonar/web/access.py`, `src/sonar/web/templates/login.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_auth_pages.py`, `tests/web/test_static.py`, `SPEC.md`
Test first: in test_auth_pages.py, `/auth/google?mode=code` then the callback for a listed verified email
  gives 302 to `/` and GET / answers 200 (a leftover cached link still signs in); today it renders the code
  page, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_auth_pages.py tests/web/test_static.py` passes, the new mode=code
  regression test and the manifest tests included
- C2 [cmd] `test "$(git diff --name-only 57a4928^ -- src tests ':!src/sonar/web/static/sonar.css' | tr '\n' ' ')" = "src/sonar/web/static/manifest.webmanifest src/sonar/web/templates/base.html tests/web/test_auth_pages.py tests/web/test_static.py "`
- C3 [cmd] `! git grep -n -i -E "sign_in_code|sign_in\.js|SignInCodes|code_mode|mode=code|/auth/code|one-time-code" -- src tests SPEC.md ':!tests/web/test_auth_pages.py'`
- C4 [review] `git diff 57a4928^ -- tests/web/test_auth_pages.py` holds only the manifest test and the mode=code
  regression test; `git diff 57a4928^ -- SPEC.md` is exactly one added manifest-only bullet as in D11;
  sonar.css is rebuilt
- C5 [cmd] `uv run pytest -q -x && uv run ruff check . && uv run ruff format --check .`

## N10 login visual check
Do: gate, pre-authorized (D13). Start the scratch launcher (session scratchpad, never the repo): `create_app`
  on a temp DB with `AuthSettings` (dummy client id and secret, a random 32+ character session secret,
  base_url http://127.0.0.1:8000) and a stand-in Google whose `authorize_redirect` stores a state key in the
  session and redirects to /auth/callback, and whose `authorize_access_token` returns a verified
  owner@example.com; serve it on 127.0.0.1:8000 and run `uv run sonar allow-email owner@example.com --db <tmp db>`.
  Open /auth/login, then tap Sign in with Google. Check the login page at desktop and 375px, light and dark
  (read_page first; scaled screenshots only where layout matters).
Done when:
- C1 [visual] /auth/login shows the card with only the "Sign in with Google" button: no code field, no "Have a
  sign-in code?" text, no overflow at 375px, legible in light and dark
- C2 [visual] Sign in with Google lands on the dashboard signed in as owner@example.com

## N06 owner iPhone check
Do: gate for the owner (D14, D15, D16): the owner deploys the committed tree to the server themselves, deletes
  the Sonar icon from the iPhone home screen and adds it again from Safari (Share, Add to Home Screen), so iOS
  reads the current manifest. Then in the home-screen app: tap Sign in with Google, finish Google, then close
  the app fully and relaunch it; finally sign in once from plain Safari.
Done when:
- C1 [human] after Google the home-screen app shows the dashboard inside the app, with no Safari chrome,
  status bar overlay or close button
- C2 [human] relaunching the home-screen app opens signed in, without the login page
- C3 [human] sign-in from plain Safari goes straight to the dashboard

## N07 plan acceptance
Do: Whole-plan check: the full verify, the CSS against a fresh build, SPEC §11 (SPEC.md:162) and §12
  (SPEC.md:178) for the login page, and that no code sign-in is left (D16).
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [cmd] `test "$(git diff --name-only 57a4928^ -- src ':!src/sonar/web/static/sonar.css' | tr '\n' ' ')" = "src/sonar/web/static/manifest.webmanifest src/sonar/web/templates/base.html "`
- C4 [review] SPEC §11 and §12 hold for login.html: extends base.html, composes the component macros, no
  inline `<style>` or `<script>`
- C5 [review] the SPEC §13 home-screen bullet describes only the manifest (D11) and matches
  manifest.webmanifest and base.html; no migration was added; the normal callback, session length and API
  token handling are unchanged (tests/web/test_auth_pages.py, tests/web/test_auth_api_token.py)

## Log

### N01 try 1 · 2026-10-12
check: PASS 4/4

### N02 try 1 · 2026-10-12
exec: DONE · 1367 passed
- Added SignInCodes and TooManyAttempts in auth/codes.py with HMAC digests, TTL, per-client and store-wide limits
- Successful and malformed redeems both count as attempts; malformed counts as a failure
check: PASS 3/3
verify: PASS

### N03 try 1 · 2026-10-12
exec: DONE · 1375 passed
- /auth/google?mode=code flags the session; code-mode callback checks the access list, issues a code, renders bare sign_in_code.html with no-store
- create_app gains now clock and one SignInCodes; access._is_allowed made public as is_allowed_email; sonar.css rebuilt
check: PASS 3/3
verify: PASS

### N04 try 1 · 2026-10-12
exec: DONE · 1390 passed
- POST /auth/code (Origin/Referer check before redeem, 303/400/403/429), login code form, static/sign_in.js, SPEC §13 bullet, tests
- sonar.css rebuilt, unchanged: no new classes; 403/429 reuse the same inline error text
check: PASS 5/5
verify: PASS

### N06 try 1 · 2026-10-12
human: FAIL: code sign-in leaves the home-screen app
- Owner tested on iPhone against production (deployed 2bb2f42). In the home-screen app, after typing the 6-digit code on /auth/login and tapping Sign in with code, the result opens in the in-app browser overlay again (status bar and close button appear) instead of staying in the standalone app. So the POST /auth/code submit or its 303 redirect to / is treated as leaving the app scope (check manifest scope/start_url vs SONAR_BASE_URL, form target, redirect, and how iOS standalone handles form posts and redirects). Checks 2 and 3 were not reached.

### N06 replan 1 · 2026-10-12
plan: ASK D15
- cause: no web app manifest, so iOS scopes the home-screen app to the folder it was added from (likely /auth/ via the login redirect); the 303 to / leaves the scope and opens the in-app browser
- D15 proposed: public static manifest with scope / and start_url /, linked from base.html, then the owner re-adds the icon; alt: no code change, re-add from / while signed in
plan: REPLANNED +N08
- D15 confirmed: add the manifest; N08 serves a public static/manifest.webmanifest (scope and start_url /) linked from base.html
- N06 now depends on N08 and starts with the owner deleting and re-adding the home-screen icon from Safari; C1 also rules out the overlay close button

### N08 try 1 · 2026-10-12
exec: DONE · tests: 1393 passed
- Added static manifest.webmanifest (D15 keys, scope and start_url /), a rel=manifest link in base.html, manifest tests in test_static.py and test_auth_pages.py, and one sentence on the SPEC home-screen bullet
- sonar.css rebuilt with no diff; the apple-touch-icon test was added as support and passed on first run since the icon already exists
check: PASS 3/3
verify: PASS

### N06 try 1 · 2026-10-12
human: FAIL: code page has no close button after the manifest
- Owner retested on iPhone after b27a292 (manifest, scope /) was deployed and the icon re-added. Now, after Google, the code page shows inside the standalone app with no close button, so the owner cannot get back to the login page to type the code. Likely reason: with scope / the Google callback comes back in scope, so iOS ends the in-app browser and finishes the round trip in the standalone app, using the app's own cookie jar (the OAuth state check passed, since the code page rendered). If so, the normal Google flow (session cookie set on callback) now works in the home-screen app, and code mode is no longer needed. Owner suggests removing the code display, i.e. drop code mode (sign_in.js standalone switch, mode=code, the code page and maybe POST /auth/code) and let the standalone app use the plain Google sign-in. Checks 2 and 3 were not reached.

### N06 replan 2 · 2026-10-12
plan: ASK D16
- cause: with manifest scope / the Google callback returns into the standalone app, so the code page renders there with no close button; plain Google sign-in likely works in the home-screen app now
- D16 proposed: drop code mode fully (sign_in.js, mode=code, code page, code form, POST /auth/code, codes.py, now clock, SPEC bullet to manifest only), keep the manifest; alt: remove only sign_in.js and keep the code flow dormant
- no brief, graph or intent change until D16 is answered; N06 is at rp 2 of the 2-replan budget
plan: REPLANNED +N09,N10
- D16 confirmed: drop code mode fully; with manifest scope / the Google callback returns into the standalone app, so plain Google sign-in suffices
- N09 removes codes.py, code mode, code page, code form, POST /auth/code, sign_in.js, the now clock and their tests, keeps the manifest, cuts the SPEC bullet to the manifest, adds a mode=code regression test
- N10 visual gate on the login page; N06 now depends on N10 and checks plain Google sign-in plus relaunch in the home-screen app; N07 drops the code criteria; Intent and goal rewritten, D1-D10 void

### N09 try 1 · 2026-10-12
exec: DONE · 1347 passed
- Removed code store, code mode, code page/form, POST /auth/code, sign_in.js, now clock and tests; restored pre-plan auth.py, app.py, access.py, login.html
- Added mode=code regression test; SPEC bullet cut to manifest-only; sonar.css rebuilt
check: PASS 4/4
verify: FAIL C4
- C4 src/sonar/web/static/sonar.css:2 - not fully rebuilt: a fresh build with the AGENTS.md command differs, the committed file still carries --text-4xl, --text-4xl--line-height and --tracking-widest theme variables that no template or source uses - expected output identical to a rebuild from the current tree

### N09 try 2 · 2026-10-12
exec: DONE · 1347 passed
- Rebuilt sonar.css from src only; the plan file mentions text-4xl and tracking-widest and tailwind auto-scans it
- Build run on a copy of src so .plan does not leak classes in
check: PASS 4/4
verify: PASS
