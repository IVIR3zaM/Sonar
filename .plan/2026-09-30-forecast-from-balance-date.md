# Forecast from the balance date
status: RUNNING
created: 2026-09-30 · updated: 2026-09-30
goal: every dashboard estimate is anchored on the date the data is known up to (the estimate date), not the calendar day, and the dashboard says "Estimated from <date>"
request: dashboard forecast (payday projection, due payments, Keep the lights on days, shortfall, runway) uses the real today although the balance may be older; base it on the balance/transactions date and show that date; payday and days to payday stay sensible
spec: SPEC §8, §9, §13 (Forecast window, Keep the lights on months, Expected at payday)
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
budgets: 2 tries per brief · 2 replans per node

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | anchor the dashboard on the estimate date | exec | - | opus/opus | 2 | 0 | DONE | |
| N02 | show the estimate date and a passed payday | exec | N01 | sonnet/sonnet | 1 | 0 | RUNNING | |
| N03 | visual check | gate | N02 | - | 0 | 0 | TODO | |
| N04 | plan acceptance | check | N01,N02,N03 | -/sonnet | 0 | 0 | TODO | |

## Open questions

- none (resolved: the estimate date is the balance's as-of date; when the data predates a passed payday, forecast the cycle the data is in and show a notice linking to Import)

## Nodes

### N01 anchor the dashboard on the estimate date
Do: In `load_dashboard`, derive the estimate date as the balance's as-of date and expose it as a new `Dashboard.estimated_from: date | None` (None without a balance). Compute the next payday as the first payday strictly after the estimate date instead of after `today`; the window stays [estimate date + 1, payday − 1]. Compute `forecast.fixed_costs` and `debt_overview` as of the estimate date (falling back to `today` when there is no balance), so debt paid-off status and next-due dates match the forecast. `days_to_payday` stays `(payday − today).days`, the calendar count, and may be negative when the data predates the payday; the forecast then covers the cycle the data is in (N02 shows the notice). Add the SPEC §13 amendment bullet below.
Spec: SPEC §9, §13 (Forecast window at SPEC.md:229, months at SPEC.md:240); src/sonar/dashboard.py:26-51 (Dashboard), :53-60, :79, :89-96, :112
Read: src/sonar/dashboard.py; src/sonar/payday.py:43-53; tests/test_dashboard.py:1-126 (helpers `_configured`, `_monthly`, `_insert_import_balance`), :181-214; SPEC.md:225-241
Write: src/sonar/dashboard.py, tests/test_dashboard.py, SPEC.md
Test first: in tests/test_dashboard.py (salary day 26; paydays 2026-09-25 and 2026-10-26), a balance of 2026-09-20 loaded with today 2026-09-28 gives payday 2026-09-25, window_days 4, days_to_payday −3, and a monthly payment on day 1 is not in `due`; today currently yields payday 2026-10-26 and fails.
Done when:
- C1 `Dashboard` has `estimated_from`; a test shows it equals the balance's as-of date, and is None with no balance.
- C2 A test with balance 2026-09-20, today 2026-09-28 asserts payday 2026-09-25, window_days 4, days_to_payday −3, and that a monthly payment due 2026-10-01 is absent from `due` while one due 2026-09-22 is present.
- C3 A test with balance 2026-09-09, today 2026-09-10 asserts payday 2026-09-25, window_days 15, days_to_payday 15 (the common one-day-old case).
- C4 A test shows a fixed-cost row's `next_due` is computed from the estimate date: monthly payment on day 22 with no payment booked, balance 2026-09-20, today 2026-09-28 → next_due 2026-09-22.
- C5 The parametrized case `as_of=2026-09-30` of `test_balance_on_or_after_the_day_before_payday_leaves_nothing_due` (tests/test_dashboard.py:202) is replaced by a test that a balance dated 2026-09-30 forecasts to payday 2026-10-26; the 2026-09-24 case still leaves nothing due.
- C6 `load_dashboard` passes the estimate date (or `today` without a balance) to `forecast.fixed_costs` and `debt_overview`; `today` is used only for `days_to_payday`, and no domain code calls `date.today()`.
- C7 SPEC.md §13 ends with one new bullet: "Estimate date (§9, overrides "today" in the dashboard): every dashboard estimate is based on the balance's as-of date, the estimate date: the next payday is the first payday after it, the window is [estimate date + 1, payday − 1], and fixed costs and debt remainders are computed as of it; days to payday still count from today and are negative when the data predates that payday. The dashboard shows "Estimated from <date>", labels the runway marker "Balance on <date>", and when the payday has passed it says the data ends before it and links to Import."
- C8 the verify command exits 0.
Findings:
- try 1: C6 src/sonar/dashboard.py:67 - `debt_overview(conn, estimate_date)` has no test: a scratch copy with `today` swapped back in still passes the whole suite (807 passed), so nothing checks that debt paid-off status and remainders are computed as of the estimate date. This breaks the "test for every behavior" rule. - expected: a test in tests/test_dashboard.py that fails when `debt_overview` gets `today` instead of the balance's as-of date

### N02 show the estimate date and a passed payday
Do: On the dashboard hero, show "Estimated from <date>" from `dashboard.estimated_from`, rename the runway legend "Balance today" to "Balance on <date>", and when `dashboard.days_to_payday < 0` show a notice that the data ends before that payday with a link to `/import`. Make `days_until` read "1 day ago" / "N days ago" for negative values. Rebuild `sonar.css`.
Spec: SPEC §9, §12, §13 (the Estimate date bullet from N01); src/sonar/templates/index.html:45-90 (hero, balance and payday stats at :72-79, legend at :88); src/sonar/display.py:65-75; CLAUDE.md Conventions UI
Read: src/sonar/templates/index.html:40-97; src/sonar/templates/components/amount.html:16-18 (`date` macro); src/sonar/display.py:65-75; tests/test_display.py (grep `days_until`); tests/test_dashboard_page.py:1-60 (helpers), :160-180, :270-282, :475-485; tests/html.py
Write: src/sonar/templates/index.html, src/sonar/display.py, tests/test_display.py, tests/test_dashboard_page.py, src/sonar/static/sonar.css
Test first: a page test with salary day 26, today pinned, and a manual balance one day old finds `#estimated-from` whose `time[datetime]` is the balance date and whose text starts with "Estimated from"; it fails because the element does not exist.
Done when:
- C1 `#estimated-from` renders inside `#hero` with text "Estimated from <date>" and a `<time datetime="YYYY-MM-DD">` equal to the balance's as-of date, via the `date` macro.
- C2 `#runway [data-legend=balance]` text starts with "Balance on" and contains a `time[datetime]` equal to the as-of date; test_dashboard_page.py:177 is updated accordingly.
- C3 With a balance dated before a payday that is before today, the page shows `#stale-data` (role="status") containing the payday's `time[datetime]` and a link with href `/import`, and `#days-to-payday` reads "N days ago" with `data-days` negative; with a fresh balance `#stale-data` is absent.
- C4 `days_until(-1) == "1 day ago"` and `days_until(-3) == "3 days ago"`; the existing 0, 1 and N cases are unchanged.
- C5 No inline `<style>`; amounts use `amount`/`eur`, dates the `date` macro; sonar.css rebuilt with the Setup command and committed.
- C6 the verify command exits 0.
Findings:
- none

### N03 visual check
Do: gate. The orchestrator starts the app on a temp DB, imports the sample in samples/, sets salary day 26, and checks `/` at desktop and 375px, light and dark (read_page first; scaled screenshots only where layout matters). State A: before setting a manual balance, note the import balance's as-of date; if it is before 2026-09-25, the page shows the passed-payday state. State B: set a manual balance as of 2026-09-29.
Done when:
- C1 State B: the hero shows "Estimated from 29 Sep 2026", payday 26 Oct 2026 "in 26 days", the runway legend "Balance on 29 Sep 2026", and no `#stale-data`.
- C2 State A (when the import balance predates 25 Sep 2026): `#stale-data` shows with an Import link, and "days ago" text for the payday.
- C3 In all four views the new line and notice wrap without overflow at 375px and are legible in light and dark.
Findings:
- none

### N04 plan acceptance
Do: check the whole plan against its goal.
Done when:
- C1 the verify command exits 0
- C2 SPEC §11 still holds for the areas this plan touched (dashboard due list, Keep the lights on range, payday projection, traffic light, salary day and weekend paydays)
- C3 src/sonar/dashboard.py derives payday, window, fixed costs and debts from the estimate date; `today` feeds only `days_to_payday`
- C4 SPEC §12 UI acceptance holds for index.html, and SPEC §13 has the Estimate date bullet matching the built behavior
Findings:
- none
