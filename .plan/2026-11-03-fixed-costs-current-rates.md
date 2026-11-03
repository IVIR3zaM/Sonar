# Fixed costs at current rates
status: DONE
created: 2026-11-03 · updated: 2026-11-03
goal: the Fixed costs Monthly equivalent and the dashboard fixed breakdown count every payment at its current rate, with an end note for debts ending within a year
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The owner reads the fixed-cost monthly figures as what each payment really costs a month today, so an
installment with a few payments left shows its full rate instead of a diluted average, and a short note tells
when it ends.

In scope: A new monthly rule in `forecast.py` shared by `fixed_costs` and `fixed_breakdown`: each counted source's
current amount divided by its interval in months, summed and rounded with the existing largest-remainder method;
an `ends_on` per breakdown payment for a schedule ending within the next 12 months, carried in `/api/dashboard`
and shown as a small "ends <Mon YYYY>" note in the breakdown; tests moved to the new rule; a SPEC §13 amendment.

Out of scope: Pay-cycle forecast columns, bare-minimum cycle figures, the debts page and payoff math, the Fixed
costs rows table, and the breakdown's grouping, labels, shares and layout.

Constraints: AGENTS.md rules: strict TDD, pure functions with `today` a parameter, integer cents (exact rationals
allowed in between, never float), DB access only via stores, `components/` macros, `amount` macro, dates through
the `date` filter or `charts.month_label`, no inline style, page tests on ids and `data-*` through `tests/html.py`,
`sonar.css` rebuilt and committed. Readable at 375px. Decisions D1-D9.

Definition of done: A fixture monthly installment with 6 payments left counts at its full rate in the Monthly
equivalent and the breakdown and shows its end note; a quarterly payment counts at amount / 3; groups still sum to
the Monthly equivalent exactly; the Bare minimum gap note still renders; the full verify passes; the visual gate
passes on the dashboard at desktop and 375px, light and dark; the final check confirms SPEC §11 and §12.

## Decisions

- D1 A source counts at the amount of its period valid on the estimate date (latest-started wins, as `_current_or_next_period`, `forecast.py:338`); a source with no such period (ended, paid off, or paused now even if it resumes within the year) is left out of both figures | confirmed
- D2 A source that has not started yet (every period starts after the estimate date, e.g. a new installment whose first payment is next month): counts at its first period's rate when that period starts within 12 months of the estimate date, else left out | confirmed
- D3 A payment linked to a meter's schedule (`SupplierDates`, hand-entered advance dates): keeps today's rule, its planned cents in the 12 calendar months from the estimate date's month / 12, because the schedule's dates are its real cadence | confirmed
- D4 Monthly per source is the exact rational amount / interval months (no float); the Monthly equivalent is their sum rounded half up once; the breakdown floors each, hands the leftover cents to the largest remainders, ties by payment name, so groups sum to the Monthly equivalent exactly | confirmed
- D5 End date: `ends_on` is the `until` of the source's latest-starting period, set on any counted source (debt schedules, and a recurring payment with a set last date) when it is on or before the estimate date + 12 months, else null | confirmed
- D6 Breakdown payment gets `ends_on` (`date | None`); `/api/dashboard` `fixed_breakdown.groups[].payments[]` carries it as ISO date or null through `_jsonable`; the page shows "<amount> · ends <Mon YYYY>" (e.g. "55,18 € · ends Apr 2027") with `charts.month_label`, muted, hook `data-field="ends"` with `data-date` ISO; no note when null | confirmed
- D7 The Fixed costs card and the Bare minimum gap note (`index.html:302-305`) change only through the new number; their markup stays | confirmed
- D8 The visual gate is pre-authorized: config `visual_recipe` on `$TMPDIR/sonar-visual.db`, after `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`; the gate may add a test installment to that temp DB | confirmed
- D9 The behavior is one new SPEC §13 bullet "Fixed costs current rates (§9, §12, API)", overriding the Monthly equivalent rule and D1 of §13 Fixed costs breakdown | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | current-rate math and SPEC | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 1 | DONE | |
| N03 | end note and API | exec | N02 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N04 | visual check | gate | N03 | -/sonnet | 0 | 0 | DONE | |
| N05 | plan acceptance | check | N04 | -/sonnet | 1 | 0 | DONE | |

## N01 preflight
Do: Confirm the starting point: verify passes on the untouched tree, the Tailwind CLI builds (the only download),
  `samples/` and `data/categories.toml` exist and the category import command answers for the gate, and the repo is
  writable. Tests need no network. A dirty tree (`.gitignore`, `.claude/launch.json`, this plan) is fine.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C3 [cmd] `test -n "$(ls samples/*.csv 2>/dev/null)" && test -f data/categories.toml`
- C4 [cmd] `uv run sonar import-categories --help` exits 0
- C5 [cmd] `test -w .git/index && git status --porcelain >/dev/null`

## N02 current-rate math and SPEC
Do: In `src/sonar/cashflow/forecast.py`, replace `_year_total` (`forecast.py:277`) as the per-source figure with one
  helper giving each source's exact monthly amount (D1-D4) and its `ends_on` (D5); `fixed_costs` (`forecast.py:203`)
  and `fixed_breakdown` (`forecast.py:219`) both use it, keeping the largest-remainder apportioning. Add
  `ends_on: date | None = None` to `BreakdownPayment` (`forecast.py:91`). Update tests that assert the old 12-month
  average to the new rule. Append one SPEC §13 bullet after `SPEC.md:272` stating D1-D6 (D9).
Context: D1 count at the amount of the period valid on the estimate date (latest-started wins, `forecast.py:338`);
  no such period (ended, paid off, paused now) = left out. D2 not started yet (all periods start later) = its first
  period's rate when it starts within 12 months of the estimate date, else left out. D3 meter-linked sources
  (`source.supplier`) keep the old rule: `_planned` (`forecast.py:286`) cents over the 12 calendar months from the
  estimate month / 12. D4 exact rational amount / interval (e.g. `fractions.Fraction`, never float); total = sum
  rounded half up once; breakdown floors each, leftover cents to the largest remainders, ties by name. D5 `ends_on`
  = `until` of the latest-starting period when <= estimate date + 12 months (`schedule.add_months`), else None.
  D6 (SPEC text only here; N03 builds it): `/api/dashboard` `fixed_breakdown.groups[].payments[]` carries `ends_on`
  as ISO date or null; the page shows "<amount> · ends <Mon YYYY>" (e.g. "55,18 € · ends Apr 2027"), muted, hook
  `data-field="ends"` with `data-date` ISO, no note when null. D9 the bullet is titled "Fixed costs current rates
  (§9, §12, API)" and says it overrides the monthly-equivalent rule (`SPEC.md:136`), the 12-month averaging and
  yearly-cents apportioning sentences of §13 Fixed costs breakdown (`SPEC.md:267`), and its payments shape
  `{name, monthly_cents}` (now plus `ends_on`).
  Debt schedules end with a one-day final period (`src/sonar/debts/model.py:219-235`), so the latest-starting
  period's `until` is the debt's end. Update `EQUIVALENT_MONTHS`' comment and the docstrings to say why.
  Tests likely on the old rule: `tests/cashflow/test_forecast.py:47-70,133-140,175-179`,
  `tests/cashflow/test_fixed_breakdown.py:20-60,115-128`, `tests/cashflow/test_service.py:168`,
  `tests/cashflow/test_service_fixed_breakdown.py:114`, `tests/web/test_dashboard_page.py:379`.
Read: `src/sonar/cashflow/forecast.py`, `src/sonar/debts/model.py:184-235`, `src/sonar/recurring/schedule.py:20-40`,
  `tests/cashflow/test_fixed_breakdown.py`, `tests/cashflow/test_forecast.py:1-180`, `SPEC.md:136,266-272`
Write: `src/sonar/cashflow/forecast.py`, `tests/cashflow/**`, `tests/web/test_dashboard_page.py`, `SPEC.md`
Test first: a monthly installment-shaped source of 5518 with 6 payments left (final period last) gives breakdown
  monthly 5518, `ends_on` its last date, and the same 5518 in `fixed_costs(...).monthly_equivalent_cents`; a
  quarterly 3001 counts 1000.33 (breakdown 1000 or 1001 by remainder, total exact); a paused, an ended and a far
  not-yet-started source are left out; a meter-linked source keeps its 12-month figure; a source ending after
  13 months has `ends_on` None.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow tests/web/test_dashboard_page.py`
- C2 [review] the tests cover D1 (current amount, paused and ended left out), D2, D3, D4 (quarterly / 3, exact sum
  across mixed intervals including a non-divisor of 12) and D5 (inside, outside and open-ended)
- C3 [review] one helper feeds both `fixed_costs` and `fixed_breakdown`; no float; `today` stays a parameter;
  `fixed_due`, `cycle_costs` and `_row` behave as before
- C4 [review] the SPEC §13 bullet states D1-D6 in plain words and names the three overridden rules listed in D9
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 end note and API
Do: In the breakdown payment list (`src/sonar/web/templates/index.html:241-246`), after the amount add, when
  `payment.ends_on` is set, a small muted " · ends <Mon YYYY>" span with `data-field="ends"` and
  `data-date="<ISO>"`, the month from `charts.month_label` (`src/sonar/web/charts.py:313`). Prove `/api/dashboard`
  carries `ends_on` per payment. Rebuild and commit `sonar.css`.
Context: Done in N02: `BreakdownPayment(name, monthly_cents, ends_on: date | None)` in
  `src/sonar/cashflow/forecast.py`; `ends_on` is set only for a schedule ending on or before the estimate date + 12
  months; `/api/dashboard` serializes it via `_jsonable` (`src/sonar/web/api/_common.py:52`) as ISO or null (D6).
  D7 the Fixed costs card and `#bare-minimum-gap-note` markup stay. Amounts via the `amount` macro with
  `colored=false`; the line must still fit at 375px (wrap, no horizontal scroll); no inline `<style>`.
  Seed helpers: `tests/web/test_dashboard_fixed_breakdown.py:15-60` (an installment posted on `/debts/installments`),
  `tests/web/test_dashboard_bare_minimum.py:1-40`; page helpers `tests/html.py:11-44`.
Read: `src/sonar/web/templates/index.html:219-262`, `tests/web/test_dashboard_fixed_breakdown.py`,
  `tests/web/test_api_dashboard.py:1-50`, `tests/html.py`
Write: `src/sonar/web/templates/index.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_dashboard_fixed_breakdown.py`, `tests/web/test_api_dashboard.py`
Test first: a dashboard with a monthly installment that has 6 payments left and a monthly manual payment shows the
  installment's `[data-payment]` amount at its full rate with `[data-field=ends]` whose `data-date` is its end and
  whose text reads "ends <Mon YYYY>", the manual payment has no `[data-field=ends]`, and `/api/dashboard`
  `fixed_breakdown` payments carry `ends_on` ISO for the installment and null for the other; the
  `#monthly-equivalent` and `#bare-minimum-gap-note` monthly field equal the breakdown total.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_dashboard_fixed_breakdown.py tests/web/test_api_dashboard.py tests/web/test_dashboard_bare_minimum.py`
- C2 [review] tests assert only ids and `data-*` through `tests/html.py`; they cover the end note present and
  absent, the API `ends_on` ISO and null, and the gap note still showing the Monthly equivalent
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-check.css" --minify && cmp "$TMPDIR/plz-check.css" src/sonar/web/static/sonar.css`
  shows `sonar.css` is rebuilt from the current templates
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 visual check
Do: gate, pre-authorized (D8). Run `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`,
  then start the app per config `visual_recipe` on `$TMPDIR/sonar-visual.db`. Import the newest file in `samples/`
  on /import; on /settings set salary day 26 and a balance as of the sample's last booking date. On /debts add an
  installment "Visual check plan", monthly, rate 55,18 €, total 12 x the rate, first payment 6 months before the
  balance date's month, so 6 payments are left. Check / at desktop and 375px, light and dark (read_page first,
  scaled screenshots only where layout matters), comparing with `GET /api/dashboard` `fixed_breakdown` and
  `fixed_costs.monthly_equivalent_cents`. Open the group holding the installment, then stop the app.
Done when:
- C1 [visual] the Fixed costs card's Monthly equivalent equals the breakdown header total and
  `/api/dashboard` `fixed_breakdown.total_cents`; the Bare minimum "Where it goes" gap note shows the same figure
- C2 [visual] the installment's payment line reads "55,18 € · ends <Mon YYYY>" matching its `ends_on`; payments
  without an end in the next 12 months show no note
- C3 [visual] at 375px the payment lines wrap without overflow or cut-off text; light and dark are both readable

## N05 plan acceptance
Do: Whole-plan check: run the full verify, then confirm SPEC §11 (acceptance checklist) and §12 (UI) still hold for
  the dashboard and that the new §13 bullet matches the code.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [review] SPEC §11 items touching the dashboard and fixed costs (`SPEC.md:162-177`) still hold; pay-cycle
  columns, bare-minimum cycle figures and debts page math are unchanged in behavior
- C3 [review] SPEC §12 UI rules hold for the end note: `base.html` page, `components/` macros, `amount` for money,
  no inline `<style>`, page tests on ids and `data-*`, `sonar.css` rebuilt and committed
- C4 [review] the SPEC §13 "Fixed costs current rates" bullet matches `forecast.py`, the API `ends_on` key and the
  template, including D1-D6

## Log

### N01 try 1 · 2026-11-03
check: PASS 5/5

### N02 try 1 · 2026-11-03
exec: BLOCKED · The brief requires a SPEC bullet covering D1-D6 but defines only D1-D5; D6 is needed before writing the behavioral amendment.
check: PASS 2/2

### N02 replan 1 · 2026-11-03
plan: REPLANNED
- cause: brief asked the SPEC bullet to state D1-D6 but restated only D1-D5
- brief now restates D6 (API ends_on, end note text and hooks; SPEC text only, N03 builds it) and D9 with the exact SPEC lines it overrides (SPEC.md:136, SPEC.md:267 averaging, apportioning and payments shape)
- C4 reworded to check D1-D6 and the three overrides

### N02 try 1 · 2026-11-03
exec: DONE · 2216 tests passed; targeted 275 passed; ruff check and changed-file formatting passed
- Shared exact monthly-rate helper drives fixed costs and breakdown; adds ends_on and current-rate regression coverage.
- Meter-linked sources retain calendar-year planning; SPEC §13 documents D1-D6 and overridden rules.
check: PASS 2/2
verify: PASS

### N03 try 1 · 2026-11-03
exec: DONE · 2217 passed; ruff check and format clean; CSS rebuild matches
- Added conditional muted payment end notes with ISO hooks and wrapping; rebuilt sonar.css.
- Verified six-payment installment full rate, end note present/absent, API ISO/null dates, and monthly/gap totals; API serialization needed no change.
check: PASS 3/3
verify: PASS

### N05 try 1 · 2026-11-03
check: PASS 1/1
verify: PASS
