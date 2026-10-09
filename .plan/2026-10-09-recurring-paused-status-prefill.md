# Paused and ended payments on Fixed payments
status: WAITING
created: 2026-10-09 · updated: 2026-10-09
goal: On /recurring a paused or ended payment carries a status badge, and the Resume form arrives prefilled so only a date is needed.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: The owner can tell at a glance on the Fixed payments page which payments are paused (and when they come back) or have ended, and resuming a payment takes one date because amount, interval and day already hold the latest period's values.

In scope: a pure status function over a payment's schedule periods with `today` passed in (`src/sonar/recurring/schedule.py`), wiring it into the page rows (`src/sonar/web/pages/recurring.py`), a `badge` with `data-field="status"` and the Resume prefill in `src/sonar/web/templates/recurring.html`, the SPEC sentence for the page, tests written first, and the rebuilt `sonar.css`.

Out of scope: the drawer overflow at about 1024px, any API or JSON change, how periods, pause and resume behave (schedule semantics), the dashboard and Debts pages.

Constraints: AGENTS.md rules: strict TDD, pure domain code with `today` as a parameter, page tests on `data-*` hooks through `tests/html.py`, dates via the `date` macro (SPEC.md:198), amounts in form prefills via `money`, `sonar.css` rebuilt and committed, ruff check and format clean. SPEC §6 (SPEC.md:99) and the Fixed payments page line (SPEC.md:203). A template change, so the plan ends with a visual gate. Decisions D1-D6.

Definition of done: tests for the status function (active, paused, ended, not yet started) and page tests for the badge, Next due and the Resume prefill (including the error re-render) pass; the full verify is clean; the gate sees a paused and an ended payment on /recurring at desktop and 375px, light and dark.

## Decisions

- D1 Status rule: active when a period is valid on today (`SchedulePeriod.is_valid_on`, src/sonar/recurring/schedule.py:36) and then no badge; paused when none is valid today and a period starts after today, resume date the earliest such `starts_on`; ended when none is valid today and none starts later, end date the latest `until` | confirmed
- D2 A payment whose every period starts after today (added by hand with a future first due date) never ran, so it gets no badge | confirmed
- D3 The badge sits in the Name cell next to the debt badge (src/sonar/web/templates/recurring.html:71-73), the only text cell visible below sm; tone `warn` for Paused, `neutral` for Ended | confirmed
- D4 The date in 'Paused · resumes <date>' is the resuming period's `starts_on`, rendered with the `date` macro inside the badge; Next due stays `next_due_date` unchanged | confirmed
- D5 The Resume day is prefilled with the latest period's day, so an untouched submit keeps the old day instead of the resume date's day; the empty-day default (src/sonar/web/pages/recurring.py:196-197) stays for an emptied field | confirmed
- D6 SPEC: edit SPEC.md:203 in place to name the status badge and the prefilled Resume section, rather than a new §13 bullet | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | status badge and resume prefill | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N02 | visual check | gate | N01 | -/- | 0 | 0 | TODO | |

## N01 status badge and resume prefill
Do: Add a pure `schedule_status(periods, today)` to `src/sonar/recurring/schedule.py` returning None for an
  active payment or a frozen `ScheduleStatus(kind, on)` with kind "paused" (on = resume date) or "ended"
  (on = last until). Put it on each row in `_render_recurring_page` (src/sonar/web/pages/recurring.py:48-59)
  and render it with the `badge` macro (components/badge.html:8) and `data-field="status"`,
  `data-status="<kind>"`: 'Paused · resumes <date>' or 'Ended <date>'. Prefill the Resume amount (`money`),
  interval and day from `row.latest` (recurring.html:132-134), keeping the error-path values on a 400.
  Update SPEC.md:203 and rebuild `sonar.css`.
Context: D1 active = some period valid today, no badge; paused = none valid, one starts after today, date =
  earliest such starts_on; ended = none valid, none later, date = latest until. D2 every period after today
  = no badge. D3 badge in the Name cell beside the debt badge (recurring.html:71-73); tone warn for paused,
  neutral for ended. D4 the badge date is the `date` macro (amount.html:16) of starts_on; Next due unchanged.
  D5 Resume day prefilled with latest.day. D6 SPEC.md:203 edited in place: name cell also shows a
  'Paused · resumes <date>' or 'Ended <date>' badge; Resume is prefilled from the latest period.
  Edit form prefill pattern: recurring.html:111-113. CSS rebuild: AGENTS.md Setup command.
Read: `src/sonar/recurring/schedule.py`, `tests/recurring/test_schedule.py`, `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`, `tests/web/test_recurring_page.py`, `tests/web/test_recurring_page_errors.py:150-220`, `tests/html.py`
Write: `src/sonar/recurring/schedule.py`, `tests/recurring/test_schedule.py`, `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`, `tests/web/test_recurring_page.py`, `tests/web/test_recurring_page_errors.py`, `src/sonar/web/static/sonar.css`, `SPEC.md`
Test first: in tests/recurring/test_schedule.py, a period ended 2026-08-31 plus one from 2026-11-05 gives
  paused on 2026-11-05 for today 2026-09-23; the function does not exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring/test_schedule.py -k status` passes tests for active (None),
  paused with the earliest future starts_on, ended with the latest until, and all periods after today (None)
- C2 [cmd] `uv run pytest -q tests/web/test_recurring_page.py -k "status or paused or ended"` passes page tests
  (TODAY 2026-09-23): paused row's `[data-field=status]` has data-status "paused", text starting
  "Paused · resumes" and `time[datetime=2026-11-05]`, and its next_due `time` is 2026-11-05; ended row has
  data-status "ended" with `time[datetime=2026-08-31]`; an active row has no `[data-field=status]`
- C3 [cmd] `uv run pytest -q tests/web/test_recurring_page.py -k prefill` passes a test that the Resume inputs
  amount, interval_months and day equal the latest period's `money` amount, interval and day
- C4 [review] tests/web/test_recurring_page_errors.py asserts a 400 resume re-render keeps the posted amount,
  interval and day, not the prefill
- C5 [review] schedule.py has no `date.today()`; the badge uses the `badge` and `date` macros, no inline
  `<style>`; SPEC.md:203 names the badge and the prefill, no other SPEC line changed; sonar.css is rebuilt
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 visual check
Do: gate. The orchestrator starts the app on a temp DB per the config visual_recipe (import the newest sample,
  set salary day and balance), then on /recurring pauses one payment after a past date and resumes it on a
  future date, and pauses a second payment after a past date without resuming. Check /recurring at desktop
  and 375px, light and dark (read_page first; scaled screenshots only where layout matters).
Done when:
- C1 [visual] /recurring: the paused row shows a 'Paused · resumes <date>' badge in the Name cell and Next due
  shows that same date; the ended row shows 'Ended <date>'; active rows show no status badge
- C2 [visual] opening the paused row's drawer shows the Resume amount, Every (months) and Day filled with its
  latest period's values; only the date is empty
- C3 [visual] in all four views the badges wrap or fit without widening the page at 375px and are legible in
  light and dark

## Log

### N01 try 1 · 2026-10-09
exec: DONE · 1343 passed
- schedule_status + ScheduleStatus in schedule.py; paused/ended badge in Name cell; Resume prefilled from latest period (error values win); SPEC line 203 and sonar.css updated
- All-periods-in-future returns None (new payment, not paused)
check: PASS 4/4
verify: PASS
