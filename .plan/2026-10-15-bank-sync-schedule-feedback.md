# Bank sync schedule and feedback
status: WAITING
created: 2026-10-15 · updated: 2026-10-15
goal: The scheduled Enable Banking sync runs at 06:30, 09:00 and 12:00 Berlin time, and the Settings bank card shows Berlin time and a visible Sync now loading state.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: Enable Banking allows four account calls a day. The systemd timer should use three of them, at 06:30, 09:00 and 12:00 Berlin time, and leave the fourth for the owner's manual Sync now. The Settings bank card should then be easier to read: it says how often it syncs, shows the last sync in the owner's local Berlin time instead of UTC, and shows that a Sync now is in progress so the owner does not click it twice.

In scope: the timer and service unit templates under `deploy/terraform/templates/`; the matching wording in SPEC §0 and the §13 Bank sync bullet, the deploy/README.md Bank sync section and the card subtitle; a pure display filter that turns an aware UTC moment into a Berlin date and time with its zone abbreviation (CEST or CET), used for the card's Last sync; a Sync now form that, with JS, disables its button and shows a spinner and "Syncing…" while the request runs, then lands on /settings, and without JS still posts and redirects; tests written first; the rebuilt `sonar.css`; a visual gate.

Out of scope: any cap or counter on manual syncs; the sync logic in `src/sonar/banking/`; the shape of `GET /api/bank` and `POST /api/bank/sync`; Connect and Reconnect; deploying (push: none).

Constraints: AGENTS.md rules: strict TDD, page tests on ids and `data-*` through `tests/html.py`, no inline `<style>`, `sonar.css` rebuilt and committed after template changes, ruff check and format clean, a visual gate at desktop and 375px, light and dark. Domain code never calls the clock. Decisions D1-D6.

Definition of done: the timer template lists the three times; SPEC, README and the card subtitle say the same; the card's Last sync shows Berlin time with CEST or CET, tested at a CEST and a CET instant, while `GET /api/bank` keeps its ISO timestamp; Sync now has the loading state and still works as a plain form post; the full verify is clean; the gate sees the card in all four views.

## Decisions

- D1 Timer: three `OnCalendar=` lines in deploy/terraform/templates/sonar-bank-sync.timer.tftpl: `*-*-* 06:30:00 Europe/Berlin`, `*-*-* 09:00:00 Europe/Berlin`, `*-*-* 12:00:00 Europe/Berlin`; `Persistent=true` kept. Timer Description "Run the Sonar bank sync at 06:30, 09:00 and 12:00"; service Description (sonar-bank-sync.service.tftpl:2) "Sonar scheduled bank sync" | confirmed · three OnCalendar lines
- D2 Wording: SPEC.md:10 "a daily Enable Banking sync" becomes "a scheduled Enable Banking sync"; in the §13 Bank sync bullet (SPEC.md:259) "run daily at 06:30 Berlin time" becomes "run at 06:30, 09:00 and 12:00 Berlin time (leaving the fourth of Enable Banking's daily calls for Sync now)", and it gains "Settings shows the last sync in Berlin time"; deploy/README.md:263 "every day at 06:30 Berlin time" becomes "at 06:30, 09:00 and 12:00 Berlin time, leaving the fourth of Enable Banking's four daily calls for Sync now"; deploy/README.md:293 "the daily runs" becomes "the scheduled runs"; card subtitle (settings.html:80) "Deutsche Bank, read-only, synced three times a day" | confirmed · as written
- D3 Last sync display: a pure filter `berlin_time(moment)` in src/sonar/web/display.py, registered beside src/sonar/web/app.py:79, returns `display_date` of the Berlin date plus " HH:MM" of the Berlin time plus " " and the zone abbreviation from zoneinfo (`tzname()`, CEST or CET) (e.g. 2026-10-14T12:00Z -> "14 Oct 2026 14:00 CEST", 2026-12-01T12:00Z -> "1 Dec 2026 13:00 CET"); settings.html:92 uses it and drops the "UTC" suffix; the `<time datetime>` keeps the UTC ISO value; `GET /api/bank` is unchanged | confirmed · append the zone abbreviation (CEST/CET)
- D4 Time zone data: stdlib `zoneinfo.ZoneInfo("Europe/Berlin")` on the system tz database (present on macOS and the VM, whose timer already uses Europe/Berlin); no new dependency | confirmed · stdlib only
- D5 Sync now loading: form `#bank-sync` (settings.html:107) keeps `method=post action=/bank/sync` and adds `hx-post="/bank/sync"` and `hx-disabled-elt="find button"`; the button holds the spinner span `#bank-sync-spinner` (class `htmx-indicator`, the same svg as uncategorized.html:15-26, `aria-hidden`), a `data-label="idle"` span "Sync now" hidden during the request and a `data-label="busy"` span "Syncing…" shown only during it, both via Tailwind's `in-[.htmx-request]:` variant (htmx puts `htmx-request` on the form), no app.css change. POST /bank/sync (src/sonar/web/pages/bank.py:122) with header `HX-Request: true` answers 204 with `HX-Redirect: /settings`, so htmx loads the updated /settings in full; without it, 303 to /settings as now; the sync call itself is untouched | confirmed · HX-Redirect
- D6 Gate setup, pre-authorized: a scratch launcher in the session scratchpad runs `create_app` (src/sonar/web/app.py:87) on a temp DB with BankSettings, a throwaway key and a fake bank client (no network) whose `booked_transactions` sleeps about 3 s and returns no rows, seeded with a connection and a last sync at 2026-10-14T06:30Z; it is started through a new `sonar-sync-gate` entry in the untracked .claude/launch.json, following the `sonar-gate` pattern | confirmed · fake slow client, pre-authorized

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | three daily sync times | exec | - | haiku/haiku | 1 | 1 | DONE | |
| N02 | bank card Berlin time and Sync now loading | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | visual check | gate | N01,N02 | -/- | 0 | 0 | TODO | |

## N01 three daily sync times
Do: Make the bank sync timer run at 06:30, 09:00 and 12:00 Berlin time and make SPEC and the deploy README say
  so (D1, D2). No code changes; nothing under `src/` or `tests/`. If the tree already holds these exact edits,
  keep them and change nothing.
Context: D1 timer (deploy/terraform/templates/sonar-bank-sync.timer.tftpl): three lines
  `OnCalendar=*-*-* 06:30:00 Europe/Berlin`, `... 09:00:00 ...`, `... 12:00:00 ...` in place of the one;
  `Persistent=true` kept; `Description=Run the Sonar bank sync at 06:30, 09:00 and 12:00`. Service
  (sonar-bank-sync.service.tftpl:2): `Description=Sonar scheduled bank sync`.
  D2 SPEC.md:10 "a daily Enable Banking sync" -> "a scheduled Enable Banking sync". SPEC.md:259 (§13 Bank sync):
  "run daily at 06:30 Berlin time" -> "run at 06:30, 09:00 and 12:00 Berlin time (leaving the fourth of Enable
  Banking's daily calls for Sync now)"; after "`GET /api/bank` returns the status." insert
  " Settings shows the last sync in Berlin time.". deploy/README.md:263 "every day at 06:30 Berlin time" ->
  "at 06:30, 09:00 and 12:00 Berlin time, leaving the fourth of Enable Banking's four daily calls for Sync now".
  deploy/README.md:293 "the daily runs" -> "the scheduled runs". Nothing else in these files changes.
  `.gitignore` and the plan file are not this node's; leave them untouched.
Read: `deploy/terraform/templates/sonar-bank-sync.timer.tftpl`, `deploy/terraform/templates/sonar-bank-sync.service.tftpl`, `SPEC.md:8-12`, `SPEC.md:259`, `deploy/README.md:261-293`
Write: `deploy/terraform/templates/sonar-bank-sync.timer.tftpl`, `deploy/terraform/templates/sonar-bank-sync.service.tftpl`, `SPEC.md`, `deploy/README.md`
Test first: -
Done when:
- C1 [cmd] `test "$(grep -cE '^OnCalendar=\*-\*-\* (06:30|09:00|12:00):00 Europe/Berlin$' deploy/terraform/templates/sonar-bank-sync.timer.tftpl)" = 3 && grep -q '^Persistent=true$' deploy/terraform/templates/sonar-bank-sync.timer.tftpl`
- C2 [cmd] `grep -qxF 'Description=Run the Sonar bank sync at 06:30, 09:00 and 12:00' deploy/terraform/templates/sonar-bank-sync.timer.tftpl && grep -qxF 'Description=Sonar scheduled bank sync' deploy/terraform/templates/sonar-bank-sync.service.tftpl`
- C3 [cmd] `grep -qF 'by a scheduled Enable Banking sync (§13 Bank sync).' SPEC.md && grep -qF "run at 06:30, 09:00 and 12:00 Berlin time (leaving the fourth of Enable Banking's daily calls for Sync now), by Sync now" SPEC.md && grep -qF 'returns the status. Settings shows the last sync in Berlin time. With neither variable set' SPEC.md`
- C4 [cmd] `grep -qF "at 06:30, 09:00 and 12:00 Berlin time, leaving the fourth of Enable Banking's four daily calls for Sync now. With both unset" deploy/README.md && grep -qF 'shows the scheduled runs; ' deploy/README.md`
- C5 [cmd] `! grep -rnE "daily at 06:30|every day at 06:30|every morning|a daily Enable Banking|the daily runs" SPEC.md deploy/README.md deploy/terraform/templates/`
- C6 [cmd] `test -z "$(git status --porcelain -- src tests)"`
- C7 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 bank card Berlin time and Sync now loading
Do: On the Settings bank card, show Last sync in Berlin time through a new pure filter, change the subtitle, and
  give Sync now an htmx loading state (disabled button, spinner, "Syncing…") that ends on the updated /settings
  while the plain form post keeps working. Rebuild `sonar.css`.
Context: Filter: `berlin_time(moment: datetime) -> str` in src/sonar/web/display.py, stdlib
  `zoneinfo.ZoneInfo("Europe/Berlin")`, no new dependency: `display_date` (display.py:45) of the Berlin date,
  a space, the Berlin `HH:MM`, a space, the zone abbreviation from the Berlin time's `tzname()` (CEST or CET).
  Register it beside app.py:79. settings.html:92: the visible text becomes `berlin_time`, no "UTC" suffix;
  `<time datetime>` keeps `last_sync_at.isoformat()`.
  settings.html:80 subtitle: "Deutsche Bank, read-only, synced three times a day". Sync now (settings.html:106-
  108): form keeps `id=bank-sync method=post action=/bank/sync`, adds `hx-post="/bank/sync"` and
  `hx-disabled-elt="find button"`; the `button` macro in call form (components/button.html:7, as
  uncategorized.html:15-28) holds span `#bank-sync-spinner` (`htmx-indicator inline-flex`, `aria-hidden`,
  the same svg as uncategorized.html:20-25), span `data-label="idle"` "Sync now" with
  `in-[.htmx-request]:hidden`, span `data-label="busy"` "Syncing…" with `hidden in-[.htmx-request]:inline`.
  bank.py:122 `sync_now` takes `request`; when header `HX-Request` is `true` it answers 204 with
  `HX-Redirect: /settings`, else 303 to /settings as now; the sync call and its error handling are untouched.
  `GET /api/bank` (src/sonar/web/api/bank.py:33-35) is unchanged. Tests: tests/web/test_bank_pages.py (Clock
  :34, `_connected_client` :294, Sync now tests :309-350); filter tests in tests/web/test_display.py.
  CSS build command: AGENTS.md Setup.
Read: `src/sonar/web/display.py`, `src/sonar/web/app.py:70-82`, `src/sonar/web/templates/settings.html:78-114`, `src/sonar/web/templates/uncategorized.html:1-30`, `src/sonar/web/templates/components/button.html`, `src/sonar/web/pages/bank.py:120-132`, `tests/web/test_bank_pages.py:1-60`, `tests/web/test_bank_pages.py:290-360`, `tests/web/test_display.py`, `tests/html.py`
Write: `src/sonar/web/display.py`, `src/sonar/web/app.py`, `src/sonar/web/templates/settings.html`, `src/sonar/web/pages/bank.py`, `tests/web/test_display.py`, `tests/web/test_bank_pages.py`, `src/sonar/web/static/sonar.css`
Test first: `berlin_time(datetime(2026, 10, 14, 12, 0, tzinfo=UTC)) == "14 Oct 2026 14:00 CEST"` fails: no such filter.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_display.py -k berlin` passes: 2026-10-14T12:00Z -> "14 Oct 2026
  14:00 CEST", 2026-12-01T12:00Z -> "1 Dec 2026 13:00 CET", 2026-12-31T23:30Z -> "1 Jan 2027 00:30 CET"
- C2 [cmd] `uv run pytest -q tests/web/test_bank_pages.py -k "last_sync or berlin"` passes: after Sync now with
  the clock at 2026-10-14T12:00Z `#bank-last-sync time` reads "14 Oct 2026 14:00 CEST", and at 2026-12-01T12:00Z
  "1 Dec 2026 13:00 CET"; neither text contains "UTC"; the `datetime` attribute is the UTC ISO value; `GET
  /api/bank` still returns `last_sync.at` as that ISO value
- C3 [cmd] `uv run pytest -q tests/web/test_bank_pages.py -k "sync_now"` passes: `#bank-sync` keeps method
  post and action /bank/sync and has `hx-post="/bank/sync"` and `hx-disabled-elt`; its button holds
  `#bank-sync-spinner`, `[data-label=idle]` "Sync now" and `[data-label=busy]` "Syncing…"; POST /bank/sync with
  `HX-Request: true` answers 204 with `HX-Redirect: /settings` and the sync ran; without it 303 to /settings
- C4 [cmd] `uv run pytest -q tests/web/test_bank_pages.py -k subtitle` passes: `#bank-card` says "synced
  three times a day"
- C5 [review] `berlin_time` is pure and calls no clock; no inline `<style>`; bank.py changes only the response
  of `sync_now`; no new dependency in pyproject.toml; `sonar.css` is rebuilt and has the `in-[.htmx-request]`
  rules
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N03 visual check
Do: gate, setup pre-authorized (D6). The orchestrator writes a scratch launcher in the session scratchpad that
  runs `create_app` (src/sonar/web/app.py:87) on a temp DB with BankSettings, a throwaway key and a fake bank
  client (no network) whose `booked_transactions` sleeps about 3 s and returns no rows; it seeds a connection
  with a last sync at 2026-10-14T06:30Z, and it starts through a new `sonar-sync-gate` entry in the untracked
  .claude/launch.json following the `sonar-gate` pattern. Open /settings at desktop and 375px, light and dark
  (read_page first; scaled screenshots only where layout matters), then click Sync now once in one view.
Done when:
- C1 [visual] `#bank-card` subtitle reads "Deutsche Bank, read-only, synced three times a day" and Last sync
  reads "14 Oct 2026 08:30 CEST" with no "UTC", legible with no overflow at 375px, light and dark
- C2 [visual] while the slow sync runs, the Sync now button is disabled and shows the spinner and "Syncing…"
  in place of "Sync now", without changing the button row's layout at 375px
- C3 [visual] after the sync the page is /settings with the button back to "Sync now" and Last sync showing
  the new Berlin time with its zone abbreviation and status ok

## Log

### N01 try 1 · 2026-10-15
exec: BLOCKED · Verify fails at pytest collection: tests/web/test_display.py imports berlin_time from sonar.web.display, which does not exist; test_display.py and test_bank_pages.py are modified in the working tree outside this node's Write list

### N02 try 1 · 2026-10-15
exec: DONE · 1710 passed
- berlin_time filter (zoneinfo) registered; settings bank card shows Berlin time, new subtitle, htmx Sync now loading state; sonar.css rebuilt
- sync_now answers 204 + HX-Redirect for HX-Request, else 303 as before
- existing sync-now button test now reads the idle label
check: PASS 5/5
verify: PASS

### N01 try 1 · 2026-10-15
exec: DONE · tests: 1710 passed
- Edits already present in working tree and match brief: timer runs 06:30, 09:00, 12:00 Berlin; service and timer Descriptions, SPEC.md:10 and 259, README 263 and 293 updated; no further change needed
- No file changed by this try; verified C1 and C2 greps, pytest and ruff check exit 0
check: PASS 3/3
verify: FAIL C3
- C3 verify brief - the exact-wording comparison against Context cannot be evaluated: the verify brief carries no Context text, so the descriptions and the SPEC/README lines are not evidenced as exact - expected the text as in Context
- C3 git diff --stat - the stat lists .gitignore (insurance/ entry) and the plan file besides the four Write files, so the stat does not touch only the four - expected only the four Write paths in the diff

### N01 try 2 · 2026-10-15
exec: DONE · tests: 1710 passed, ruff check and format clean
- Timer runs 06:30, 09:00, 12:00 Berlin; timer and service Descriptions reworded; SPEC §13 bank sync and line 10, deploy README lines 263 and 293 updated
- Edits were already present in the tree from try 1; verified against Context, no further edits. .gitignore and plan file changes predate this node and were left untouched
check: PASS 3/3
verify: FAIL C3
- C3 SPEC.md:10, §13 Bank sync bullet, deploy/README.md:263 and :293, timer/service Description - the brief gives no Context text, so exact wording cannot be matched; not evidenced

### N01 replan 1 · 2026-10-15
plan: REPLANNED
- Cause: C3 was a [review] comparing wording against Context, which the verify brief does not carry; its git diff --stat clause also caught the pre-existing .gitignore and plan-file changes
- New brief: exact wording moved into [cmd] grep -F criteria C2-C4 (descriptions, SPEC, README); scope check is C6 git status on src and tests only; no [review] left
- Brief tells the executor to keep edits already in the tree and leave .gitignore alone; all new [cmd]s dry-run green on the current tree

### N01 try 1 · 2026-10-15
exec: DONE · tests: 1710 passed
- Timer, service, SPEC §13 and deploy README edits were already in the tree; verified C1 to C6 and kept them, no file changed
- Kept the existing tree edits as the brief allows; no further edits made
check: PASS 7/7
