# Dashboard bare minimum
status: RUNNING
created: 2026-11-03 · updated: 2026-11-03
goal: a Bare minimum card before Fixed costs, and the same figures in /api/dashboard, showing the heaviest coming pay cycle's need against the lowest recent income
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The dashboard answers "what is the least we must earn per pay cycle to keep going?" Over the next 6 pay cycles, it takes the cycle with the highest need, where need is fixed payments plus expected keep-the-lights-on spending. It sets that need against the lowest income of the last 3 complete cycles, says why months still go negative, and shows how the need drops as installments and loans end.

In scope: a new pure module `src/sonar/cashflow/bare_minimum.py` with its tests. It covers the per-cycle need over the 6 forecast cycles of `fixed_costs.cycles`, the bare minimum (the largest need) with its two parts, cycle income, residual, debt-service share, occasional spending against the residual, the debts that end between the day after the estimate date and the end of the 6th forecast cycle, and income − need per cycle. Also in scope: wiring it into `Dashboard` in `src/sonar/cashflow/service.py`, so `/api/dashboard` carries it unchanged; a "Bare minimum" card on `index.html` directly before the Fixed costs card, with page and API tests; a rebuilt `sonar.css`; and one new SPEC §13 bullet.

Out of scope: a per-category fixed breakdown, any change to the existing Fixed costs, runway, Keep the lights on, `expected_income` or traffic-light figures, settings, migrations, and other pages.

Constraints: AGENTS.md rules apply: strict TDD; pure functions with the estimate date passed in; integer cents; DB access only through stores and the service; pages compose `components/` macros, show amounts with `eur`/`amount` and dates with `date`, and have no inline style; page tests assert on ids and `data-*` through `tests/html.py`; `sonar.css` is rebuilt and committed. The confirmed Decisions below apply.

Definition of done: with a salary day, recent income and a complete lights-on month, the dashboard card shows the bare minimum with its cycle and two parts, plus income, residual, debt share, the occasional-spending explanation, the 6-cycle table and the ending debts. Otherwise it shows a hint naming what is missing. `/api/dashboard` returns the same values. The full verify passes. The visual gate passes at desktop and 375px, light and dark. The final check confirms SPEC §11 and §12.

## Decisions

- D1 Core rule, from the request: for each of the 6 `kind == "forecast"` cycles of `fixed_costs.cycles` (forecast.py:124-150), need_k = that cycle's `forecast_cents` + its lights-on part (D2). Bare minimum = the largest need_k, shown with its fixed and lights-on parts and no per-category breakdown. Income = the lowest cycle income (D3); residual = income − bare minimum; residual_k = income − need_k for each cycle (not a cumulative sum). | confirmed
- D2 Lights-on part of a cycle = the dashboard's daily expected (`lights_on_forecast(months, 1).expected_cents`, lights_on.py:151) × the cycle's day count, so the card's "a day × days" adds up exactly. When two cycles tie for the largest need, the earliest one wins. | confirmed
- D3 Cycle income: over `payday.complete_cycles(estimate_date, salary_day, 3)`, sum the credits (amount > 0) in `income` categories that were booked in the cycle's window moved back by `SALARY_DAY_DISTANCE` (7 days, recurring/detect.py:31). A salary paid up to a week early then counts in its own cycle, by the same tolerance as income.py:60. Income = the lowest total above 0. With no cycle above 0 there is no income (hint, D6). | confirmed
- D4 Debt share: the debt part of a cycle is the due occurrences of the debt schedules only (`_debt_source` per `DebtView`, service.py:459-464). Those schedules already stand in for their linked recurring payments (service.py:439-447). Any recurring payment not linked to a debt is a plain fixed cost, even in a `debt: true` category (LBS-style, unconfirmed drafts). Share = debt cents ÷ that cycle's `forecast_cents` as an integer percent, rounded half up; 0 when the cycle's fixed is 0. | confirmed
- D5 Occasional per month = the average `occasional_cents` of the latest 3 complete lights-on months (`MonthSpend`, lights_on.py:38-43, the months the lights-on part learns from), rounded half up; 0 without months. Margin = residual − occasional: below 0 is the shortfall that makes months go negative. | confirmed
- D6 The card shows numbers whenever a salary day, a cycle income (D3) and at least one complete lights-on month exist, with or without a balance (the estimate date is then today, as the Fixed costs cycles already use, service.py:139,168). Otherwise it shows a hint, picked in this order: `salary_day`, `income`, `lights_on`. The API has `bare_minimum` (null on a hint) and `bare_minimum_hint` (null or that reason). | confirmed
- D7 Ending debts: open debts (not `paid_off`) whose end date falls within [estimate date + 1, last forecast cycle end]. An installment uses `status.end_date` and a loan `status.payoff_date`, the same as `_ladder_debt` (service.py:111-126). Each row shows name, kind, end date and `rate_cents`, sorted by end date then name. Debts ending later in the current cycle are listed too. | confirmed
- D8 Layout: a full-width card (`lg:col-span-2`, like Fixed costs at index.html:218), id `bare-minimum-card`, title "Bare minimum". It holds the bare-minimum stat with its cycle; the fixed and lights-on parts as stats; income and residual; one line on the debt share; one line on occasional spending against the residual; a 6-row cycle table (cycle, fixed, lights on, need, residual, with the max cycle marked); and an ending-debts table. Both tables sit in the scrolling wrapper so they fit at 375px. | confirmed
- D9 Visual gate, pre-authorized: config `visual_recipe` on `$TMPDIR/sonar-visual.db`, first running `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"` so income and groups are categorized (local, gitignored data into a temp DB only). Then import the newest file in `samples/`, set salary day 26 and a balance as of the sample's last booking date, and compare the card with `GET /api/dashboard`. | confirmed
- D10 SPEC: exactly one new bullet at the end of §13, "Bare minimum (§9, §12, API)", stating D1-D8. Existing §9/§13 rules are unchanged. | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | bare minimum math and SPEC | exec | N01 | codex@medium/sonnet | 1 | 1 | DONE | |
| N03 | dashboard and API wiring | exec | N02 | codex@medium/sonnet | 1 | 0 | DONE | |
| N04 | Bare minimum card | exec | N03 | codex@medium/sonnet | 1 | 0 | DONE | |
| N05 | visual check | gate | N04 | -/sonnet | 0 | 0 | DONE | |
| N06 | plan acceptance | check | N05 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point: verify passes on the untouched tree, the Tailwind CLI builds (the only
  download), `samples/` and `data/categories.toml` exist for the gate, and the repo is writable. Tests need no
  network. A dirty tree (`.gitignore`, `.claude/launch.json`, this plan) is fine.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C3 [cmd] `test -n "$(ls samples/*.csv 2>/dev/null)" && test -f data/categories.toml`
- C4 [cmd] `test -w .git/index && git status --porcelain >/dev/null`

## N02 bare minimum math and SPEC
Do: Add the pure module `src/sonar/cashflow/bare_minimum.py`: frozen dataclasses, plain fields, no properties (for
  `_jsonable`, web/api/_common.py:52): `CycleNeed(start, end, days, fixed_cents, lights_on_cents, need_cents,
  residual_cents)`, `DebtEnd(name, kind, end_date, rate_cents)`, `BareMinimum(total_cents, cycle: CycleNeed,
  income_cents, residual_cents, debt_cents, debt_share_percent, occasional_cents, occasional_margin_cents, cycles:
  tuple[CycleNeed, ...], drops: tuple[DebtEnd, ...])`; `cycle_income(rows, category_types, salary_day, estimate_date)
  -> int | None` (D3); `occasional_per_month(months) -> int` (D5); `bare_minimum(cycles, lights_on_daily_cents,
  debt_due, debt_ends, income_cents, occasional_cents, estimate_date) -> BareMinimum | None` (D1, D2, D4, D7) over
  `CycleCost`s (only `kind == "forecast"`) and `DueItem`s, None without a forecast cycle. Append one bullet at the end
  of SPEC.md §13 (SPEC.md:225-265), "Bare minimum (§9, §12, API)", stating D1-D8 as below; no other SPEC change.
Context: D1 over the 6 forecast cycles need_k = `forecast_cents` + lights-on part; bare minimum = max need_k, with its
  fixed and lights-on parts; residual = income − bare minimum; residual_k = income − need_k (not cumulative). D2
  lights-on part = daily expected cents (`lights_on_forecast(months, 1)`, lights_on.py:151) × days; ties: earliest
  cycle. D3 per cycle of `payday.complete_cycles(estimate_date, salary_day, 3)` (payday.py:82) sum `income`-group
  credits booked in [start − 7, end − 7] (`SALARY_DAY_DISTANCE`, recurring/detect.py:31); income = min total > 0,
  else None. D4 debt cents = debt-schedule `debt_due` in the max cycle (unlinked recurring stays plain fixed); share =
  debt ÷ fixed, integer percent half up, 0 when fixed is 0. D5 average `occasional_cents` of the latest 3 complete
  months, half up (income.py:75), 0 without months; margin = residual − occasional, below 0 explains negative months.
  D6 (SPEC only) numbers show when a salary day, a cycle income and a complete lights-on month exist, balance or not
  (estimate date then today); else a hint, the first missing of `salary_day`, `income`, `lights_on`; the API has
  `bare_minimum` (null on a hint) and `bare_minimum_hint` (null or that reason). D7 open debts (installment
  `end_date`, loan `payoff_date`) ending in [estimate_date + 1, last forecast end], sorted by (end_date, name). D8
  (SPEC only) a full-width "Bare minimum" card right before Fixed costs: total with its cycle, fixed and lights-on
  parts, income, residual, a debt-share line, an occasional-vs-residual line, a 6-row cycle table (cycle, fixed,
  lights on, need, residual; max marked) and an ending-debts table (name, kind, end date, rate), scrolling at 375px.
Read: `src/sonar/cashflow/{forecast,income,payday,lights_on}.py`, `tests/cashflow/test_income.py`, `SPEC.md:225-265`
Write: `src/sonar/cashflow/bare_minimum.py`, `tests/cashflow/test_bare_minimum.py`, `SPEC.md`
Test first: `tests/cashflow/test_bare_minimum.py`, anonymized. (a) Forecast A 2026-11-26..12-23 (28 days, fixed
  200_000), B 2026-12-24..2027-01-25 (33 days, fixed 260_000), daily 2_500, an ignored actual and current CycleCost:
  needs 270_000 / 342_500, total 342_500 in B (lights 82_500); income 400_000: residual 57_500, residuals 130_000 /
  57_500. (b) Debt due 80_000 + 50_000 in B, 30_000 in A: debt 130_000, share 50; 1/3 → 33, 2/3 → 67, fixed 0 → 0.
  (c) Occasional 70_000 → margin −12_500; equal needs pick the earlier cycle. (d) Drops keep one ending in A..B and
  one in the current cycle after estimate_date, drop one ending on estimate_date and one after B, sorted; no forecast
  cycle → None. (e) cycle_income: salary 2 days before payday counts in that cycle; other income credits add; debits
  and non-income credits ignored; lowest cycle above 0 wins; none → None. (f) occasional_per_month: latest 3, half up.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_bare_minimum.py`
- C2 [review] Tests (a)-(f) with these numbers; module pure (no I/O, no `date.today`, no float, integer cents), fields
  as listed; D1-D5, D7 exact; `git diff SPEC.md` adds one bullet at the end of §13 stating D1-D8, nothing else.
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 dashboard and API wiring
Do: `Dashboard` (service.py:46-80) gains `bare_minimum: BareMinimum | None` and
  `bare_minimum_hint: Literal["salary_day", "income", "lights_on"] | None`. `load_dashboard` fills them in the
  initial `board` (service.py:148-173), before the early return at :174, so they work without a balance (D6),
  through a small private helper. The helper's inputs are: the board's `fixed_costs.cycles`; the lights-on
  months from `lights_on.last_known_day(rows, balance.as_of if balance else None)` and `month_spends`, as at
  service.py:202-207 and :261-264; daily = `lights_on_forecast(months, 1).expected_cents`; debt_due =
  `forecast.fixed_due` over `_debt_source(view, txs)` for every view, from estimate_date + 1 to the last
  forecast cycle's end; debt_ends from the views (open only; an Installment uses `status.end_date`, a Loan
  `status.payoff_date`, and kind as in `_ladder_debt` :111-126; a None payoff date is skipped);
  `cycle_income`; `occasional_per_month(months)`; and `estimate_date`. Every other Dashboard field keeps its value.
  `/api/dashboard` needs no route change, because `_jsonable(board)` (web/api/cashflow.py:63) carries both keys.
Context: D4 debt = debt schedules only; plain recurring payments are never debt. D6: the hint order is
  salary_day, then income, then lights_on (no complete month); numbers appear without a balance, with the
  estimate date = today. D7: open debts only, ending in [estimate_date + 1, last forecast end]. Pure math lives in
  `cashflow/bare_minimum.py` (N02); the service only gathers inputs.
Read: `src/sonar/cashflow/service.py`, `src/sonar/cashflow/bare_minimum.py`, `tests/cashflow/test_service.py`,
  `tests/web/test_api_dashboard.py`
Write: `src/sonar/cashflow/service.py`, `tests/cashflow/test_service_bare_minimum.py`,
  `tests/web/test_api_dashboard.py`
Test first: in the new file `tests/cashflow/test_service_bare_minimum.py`, reusing the helpers' shapes from
  tests/cashflow/test_service.py:44-130 and :477, :789:
  (a) Salary day, balance, salary credits in 3 complete cycles, one complete lights-on month, a monthly fixed
  payment and an installment ending in the 3rd forecast cycle, and a second installment ending in the current cycle after
  the estimate date. Expect: total == max need; the cycle's fixed_cents == the matching
  `fixed_costs.cycles` forecast_cents; drops list both installments;
  debt_cents counts the installment's rate but not the plain payment.
  (b) A recurring payment linked to that installment is counted once, as debt.
  (c) Hints: no salary day → "salary_day"; no income credits → "income"; no complete month → "lights_on";
  each with `bare_minimum` None.
  (d) The same data without a balance still gives numbers.
  In tests/web/test_api_dashboard.py, add tests: `bare_minimum` equals `_jsonable` of `_expected_board(...)`'s
  field (:30), and without a salary day it is null with hint "salary_day".
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_service_bare_minimum.py tests/web/test_api_dashboard.py tests/cashflow/test_service.py`
- C2 [review] The service only gathers inputs and calls bare_minimum.py. No existing Dashboard field changes
  value, and no existing test is edited. D4, D6 and D7 hold, and the API returns both keys.
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 Bare minimum card
Do: In `src/sonar/web/templates/index.html`, add the D8 card between the Keep the lights on card's end
  (the `{% endcall %}` after :212-215) and the Fixed costs wrapper at :218, composing `card`, `stat`, `amount`
  and `date` from `components/`, the existing table classes (:10-18) and `charts.cycle_label` for cycle labels.
  On `dashboard.bare_minimum_hint`, it shows `#bare-minimum-hint` with `data-reason` and a link to /settings
  (salary_day), /categories (income) or /lights-on (lights_on). Rebuild `sonar.css` with the Setup command.
Context: D8 hooks: `#bare-minimum` stat (amount `data-cents`) with the cycle; `#bare-minimum-fixed` and
  `#bare-minimum-lights` (lights shown as daily × days); `#bare-minimum-income`; `#bare-minimum-residual`
  (colored); `#bare-minimum-debt-share` (`data-percent`, debt amount); `#bare-minimum-occasional`
  (`data-margin`, reading "shortfall" when the margin is below 0, else "margin"); table `#bare-minimum-cycles`
  with 6 `data-row` rows, fields cycle, fixed, lights, need and residual, the max row carrying `data-max`; and
  table `#bare-minimum-drops` with fields name, kind, end_date and rate, or `#bare-minimum-no-drops` when empty.
  Both tables use `table_wrap`. No inline style, no new CSS file.
Read: `src/sonar/web/templates/index.html`, `src/sonar/web/templates/components/stat.html`,
  `src/sonar/web/templates/components/amount.html`, `src/sonar/cashflow/bare_minimum.py`, `tests/html.py`,
  `tests/web/test_dashboard_page.py`
Write: `src/sonar/web/templates/index.html`, `tests/web/test_dashboard_bare_minimum.py`,
  `src/sonar/web/static/sonar.css`
Test first: in `tests/web/test_dashboard_bare_minimum.py`, seeding the way tests/web/test_dashboard_page.py
  does (:66-111) and asserting through `tests/html.py`: (a) the card lies directly before `#fixed-card` in
  document order; (b) its values equal `load_dashboard(...).bare_minimum` (total, both parts, income, residual,
  percent, margin, the 6 cycle rows with exactly one `data-max`, the drops rows); (c) each hint reason renders
  `#bare-minimum-hint[data-reason]` and no `#bare-minimum`; (d) with no ending debts `#bare-minimum-no-drops`
  shows.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_dashboard_bare_minimum.py tests/web/test_dashboard_page.py tests/web/test_templates_hygiene.py`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n04.css" --minify && cmp "$TMPDIR/n04.css" src/sonar/web/static/sonar.css`
- C3 [review] The card uses only the components macros and the shared table classes, has no inline style,
  and has every D8 hook. The tests assert only on ids and `data-*`. No other card changes.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 visual check
Do: gate, pre-authorized (D9). Start the app per config `visual_recipe` on `$TMPDIR/sonar-visual.db` after
  `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`. Import the newest
  file in `samples/` on /import, then on /settings set salary day 26 and a balance as of the sample's last
  booking date. Check / at desktop and 375px, light and dark (read_page first, scaled screenshots only where
  layout matters), comparing the card with `GET /api/dashboard` `bare_minimum`. Then clear the salary day,
  check the hint state, and stop the app.
Done when:
- C1 [visual] the Bare minimum card sits directly before Fixed costs. It shows the total, its cycle, the fixed
  and lights-on parts, income, residual, debt share and the occasional line, each equal to `/api/dashboard`
- C2 [visual] the cycle table has 6 rows with exactly one marked max row, and the ending-debts table or its
  empty note shows
- C3 [visual] at 375px nothing is cut off and the tables scroll inside the card; light and dark are both
  readable, with residual colors legible
- C4 [visual] without a salary day the card shows the hint linking to /settings and no numbers

## N06 plan acceptance
Do: Check the whole plan against verify, SPEC §11 and §12, and the new §13 Bare minimum bullet.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n06.css" --minify && cmp "$TMPDIR/n06.css" src/sonar/web/static/sonar.css`
- C3 [cmd] `! grep -nE "float|date\.today|datetime\.now" src/sonar/cashflow/bare_minimum.py`
- C4 [cmd] `test -z "$(git diff --name-only e447ed8 -- src/sonar/migrations)"`
- C5 [review] The SPEC §11 checklist holds, and SPEC §12 UI acceptance holds for the dashboard card (base.html,
  component macros, no inline `<style>`, `eur` amounts, `date` dates, usable without script).
- C6 [review] The §13 Bare minimum bullet matches the code for D1-D8. Fixed costs, runway, Keep the lights on,
  `expected_income` and the traffic light are unchanged, and `/api/dashboard` carries `bare_minimum` and
  `bare_minimum_hint`.
- C7 [review] No tracked file holds a real name or IBAN, and the fixtures are invented.

## Log

### N01 try 1 · 2026-11-03
check: PASS 4/4

### N02 try 1 · 2026-11-03
exec: BLOCKED · C2 requires a SPEC §13 bullet stating D1–D8, but the brief defines neither D6 nor D8; their behavior must be supplied before implementation.

### N02 replan 1 · 2026-11-03
plan: REPLANNED
- cause: brief asked for a SPEC §13 bullet stating D1-D8 but did not restate D6 (hint and API null rules) or D8 (card layout)
- new brief restates D1-D8 in Context, marks D6/D8 as SPEC-only text, pins SPEC.md:225-265 and C2 to a git diff SPEC.md check; scope, files and tests unchanged

### N02 try 1 · 2026-11-03
exec: DONE · 2091 passed; ruff check clean; changed Python files formatted
- Added pure bare minimum cycle needs, income, occasional average and debt-end calculations with 15 tests.
- Appended one SPEC §13 bullet covering D1-D8; forecast cycles sorted chronologically for earliest ties.
check: PASS 2/2
verify: PASS

### N03 try 1 · 2026-11-03
exec: DONE · 2100 passed; ruff check and format clean
- src/sonar/cashflow/service.py:82 adds bare minimum and ordered hints before the balance early return; debt inputs use debt schedules.
- tests/cashflow/test_service_bare_minimum.py and tests/web/test_api_dashboard.py cover linked debts, drops, hints and numbers without a balance; quoted hint annotations preserve literal types under the category guard.
check: PASS 2/2
verify: PASS

### N04 try 1 · 2026-11-03
exec: DONE · 2105 passed; ruff clean; CSS rebuild matches
- Added bare minimum card, hints, cycle and debt-ending tables with D8 hooks.
- Daily basis derives from full-cycle lights amount and days, independent of balance setup; added five page cases.
check: PASS 3/3
verify: PASS
