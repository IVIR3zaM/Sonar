# Dashboard income runway and fixed-cost pay cycles
status: RUNNING
created: 2026-10-07 · updated: 2026-10-07
goal: The runway bar reaches out to the expected monthly income instead of shrinking with a negative balance, and the Fixed costs chart shows actual and forecast fixed costs per pay cycle instead of 12 calendar months.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The dashboard answers two questions better. First, the runway bar is measured against what a month brings in. Its right end becomes the expected monthly income: the best salary of the last 3 complete pay cycles plus the monthly equivalent of the detected recurring income. The bar ends at the balance only when the balance is higher. The stretch from the balance up to that income gets its own color, label and legend line, so an overdrawn account no longer collapses the bar. Second, the Fixed costs chart is laid out by pay cycles, payday to the day before the next payday. It shows 6 past cycles of booked fixed debits, the current cycle split into booked so far and still expected, and 6 future cycles of forecast. Colors, a legend, cycle date ranges and an estimate-date marker make actual and forecast easy to tell apart.

In scope: a pure expected-income function in `cashflow` that reuses the salary-distance rule of `recurring/detect.py` and `detect_income`; pure pay-cycle cost totals in `cashflow/forecast.py` and `cashflow/payday.py`; `load_dashboard` wiring; runway and cycle-chart geometry in `web/charts.py` and macros in `components/charts.html`; the dashboard template; the `sonar.css` rebuild; `/api/dashboard` parity (`expected_income` added, `fixed_costs.cycles` replaces `fixed_costs.months`); a SPEC §13 amendment; tests.

Out of scope: the Payoff page (it works from rows), the Keep the lights on forecast, Settings, the projection and traffic-light rules, the fixed-cost rows table and the Monthly equivalent figure (it stays as computed today).

Constraints: AGENTS.md rules: strict TDD, integer cents, the estimate date and `today` passed in as parameters, pure core with a thin service, `tests/test_architecture.py` import rules, components macros, no inline `<style>`, `eur`/`date` display, page tests through `tests/html.py` hooks, `sonar.css` rebuilt and committed after template changes, ruff clean, no dead code. Decisions D1-D13 below.

Definition of done: Pure tests prove the worked income and cycle examples in N02 and N03. The dashboard and `/api/dashboard` expose the expected income and 13 pay-cycle totals. The runway and Fixed costs card pass the visual gate at desktop and 375px, light and dark, on the real sample. SPEC §13 states the new rules. The final check passes `verify` and SPEC §11 and §12.

## Decisions

- D1 Salary of one complete cycle = the sum of credits (amount > 0) in `income`-group categories booked within 7 days (distance ≤ `SALARY_DAY_DISTANCE`, `src/sonar/recurring/detect.py:31`) of that cycle's start payday; expected salary = the highest of the 3 complete cycles before the estimate date's cycle (`payday.complete_cycles`, `src/sonar/cashflow/payday.py:82`). A salary booked a few days before its payday belongs to that payday's cycle | confirmed
- D2 Recurring income per month = the sum over `detect_income(rows, category_types, salary_day, estimate_date)` (`src/sonar/recurring/detect.py:56`) of amount_cents × 12 / interval_months, divided by 12 and rounded half up once on the total; expected monthly income = expected salary + that | confirmed
- D3 No salary history: when the expected salary is 0 the expected income is None, even with recurring income, and the runway is exactly today's (no income segment, mark or legend item) | confirmed
- D4 Runway axis: left end unchanged (min of limit, 0, balance, worst, best); right end = max(0, balance, worst, best, income). The zone segments still tile [0, width]. A `data-part="to-income"` rect from the balance to the income end, only when income > balance, is drawn over the zones in a distinct color (violet), with a `<title>`. A scale mark `income` labels the right end. A legend item `data-legend="income"` reads "Expected monthly income X (salary Y + recurring Z)". The SVG aria-label and title add the income | confirmed
- D5 Cycles come from `payday` (`current_cycle`, `complete_cycles`, plus a new `next_cycles`) anchored on the dashboard's estimate date (the balance's as-of date, else today; `src/sonar/cashflow/service.py:125`). There are 13 columns oldest first: 6 `actual`, 1 `current`, 6 `forecast` | confirmed
- D6 Actuals = the sum of |amount| of debits (amount < 0) in `fixed`-group categories (debt categories are `fixed`, so debt payments count) booked inside the cycle; the current cycle's booked part covers [cycle start, estimate date]; credits and refunds are ignored | confirmed
- D7 Forecast = `forecast.fixed_due(sources, estimate date + 1, end of the 6th next cycle)` (`src/sonar/cashflow/forecast.py:62`) bucketed by cycle, over `_fixed_sources` (`src/sonar/cashflow/service.py:279`): recurring rows plus debt schedules until their end, every interval. Its last-paid tolerance keeps an early-booked payment from being counted twice | confirmed
- D8 Without a salary day `fixed_costs.cycles` is empty; the card hides the chart and table and shows a hint linking to `/settings`; the Monthly equivalent and rows table stay | confirmed
- D9 Data shape: `CycleCost(start, end, kind: "actual"|"current"|"forecast", booked_cents, forecast_cents)` with a `total_cents` property, both parts ≥ 0. `FixedCosts.cycles` replaces `FixedCosts.months`, and `MonthTotal` leaves the public shape. The Monthly equivalent keeps its 12-calendar-month basis privately. `ExpectedIncome(salary_cents, recurring_cents, total_cents)` becomes `Dashboard.expected_income`. JSON: `/api/dashboard` drops `fixed_costs.months` and gains `fixed_costs.cycles` and `expected_income` (object or null) | confirmed
- D10 Chart look: actual and the current cycle's booked part are solid sky; forecast parts are amber at lower opacity; the peak highlight is dropped because amber now means forecast. The current column stacks booked under forecast. A marker over the current column (`data-part="estimate"`) is labelled with the short estimate date, titled "Booked up to <date>, forecast after". Axis labels are rotated cycle ranges such as "25 Sep – 24 Oct". The legend has Actual, Forecast and the estimate marker | confirmed
- D11 The table: summary "Pay-cycle totals as table", id `cycles`, columns Cycle (range), Type (Actual, Current, Forecast), Booked, Forecast, Total, one `data-row` per cycle with `data-field` hooks | confirmed
- D12 Pre-authorized mid-run: rebuild and commit `src/sonar/web/static/sonar.css` after template changes; start the app on a temp DB with the real sample, salary day and balance set, for smoke and visual runs (N05, N06, N08, N09) | confirmed
- D13 The N08 gate needs a real export covering at least 7 months to fill 6 actual pay cycles; the only fixture (`tests/fixtures/db_girokonto.csv`, 4 days of rows) cannot. The owner copied a Deutsche Bank export (2026-01-01 to 2026-10-07, about 9 months) into `samples/` (gitignored, `.gitignore:1`); N08 uses it and N01 is re-run unchanged | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/haiku | 1 | 1 | DONE | |
| N02 | expected monthly income | exec | N01 | sonnet/sonnet | 2 | 0 | DONE | |
| N03 | fixed costs per pay cycle | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | dashboard and API wiring | exec | N02,N03 | sonnet/sonnet | 2 | 0 | DONE | |
| N05 | runway to income | exec | N04 | opus/sonnet | 0 | 0 | TODO | |
| N06 | pay-cycle chart and table | exec | N05 | opus/sonnet | 0 | 0 | TODO | |
| N07 | SPEC amendment | exec | N04 | haiku/sonnet | 0 | 0 | TODO | |
| N08 | visual check of the dashboard | gate | N06,N07 | -/sonnet | 0 | 0 | TODO | |
| N09 | plan acceptance | check | N08 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point before any work. The untouched tree passes verify, the Tailwind build runs, the repo is writable for the per-node commits, and `samples/` has a file for the visual gate.
Context: Tailwind also scans untracked, non-ignored files such as `.plan/*.md`, so a build into the tracked `sonar.css` can differ from HEAD. That is expected. The preflight builds into a temp file and never writes the tracked `src/sonar/web/static/sonar.css`. A stray rebuilt `sonar.css` is generated output and is reset to HEAD first (pre-authorized; never hand-edited, AGENTS.md).
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `git checkout -- src/sonar/web/static/sonar.css && TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "${TMPDIR:-/tmp}/sonar-preflight.css" --minify && test -s "${TMPDIR:-/tmp}/sonar-preflight.css" && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [cmd] `test -w .git && git rev-parse --abbrev-ref HEAD`
- C4 [cmd] `test -n "$(ls samples/)"`

## N02 expected monthly income
Do: Add a new pure module `src/sonar/cashflow/income.py` with a frozen `ExpectedIncome(salary_cents, recurring_cents, total_cents)` and `expected_income(rows, category_types, salary_day, estimate_date) -> ExpectedIncome | None`. It holds the best salary of the last 3 complete pay cycles plus the monthly equivalent of the detected recurring income, and None without salary history. The module docstring says why the salary is matched by payday distance.
Context: D1: per complete cycle, sum the credits (> 0) in `income`-group categories booked within `SALARY_DAY_DISTANCE` days (≤ 7, `src/sonar/recurring/detect.py:31`) of the cycle's start payday. Cycles come from `payday.complete_cycles(estimate_date, salary_day, 3)` (`src/sonar/cashflow/payday.py:82`). Salary = the max of those sums. A credit at payday − 2 counts for that payday, never for the cycle it is booked in.
  D2: recurring = the sum over `detect_income(rows, category_types, salary_day, estimate_date)` (`detect.py:56`) of amount_cents × 12 / interval_months, divided by 12 and rounded half up once on the total (integer math, as `forecast.py:112`).
  D3: salary 0 → None, even with recurring income. The group name is `groups.INCOME` (`src/sonar/categorization/groups.py`). `Row` is `detect.Row` (`detect.py:34`). Integer cents only; no clock reads.
Read: `src/sonar/cashflow/payday.py`, `src/sonar/recurring/detect.py:26-70`, `src/sonar/categorization/groups.py:1-30`, `tests/cashflow/test_payday.py`, `tests/recurring/test_detect.py:1-60`
Write: `src/sonar/cashflow/income.py`, `tests/cashflow/test_income.py`
Test first: The worked example uses salary day 25 and estimate date 2026-10-07. The complete cycles start 2026-08-25, 2026-07-24 and 2026-06-25. Income credits: 300000 on 2026-06-25; 320000 on 2026-07-24 plus 10000 on 2026-07-27; 310000 on 2026-08-22; 400000 on 2026-09-25 (current cycle, ignored); 9000 on 2026-08-03 (10 days off, ignored). A child allowance of 25500 is booked on 2026-07-15, 08-15 and 09-15. A 50000 credit in a non-income category near payday is ignored. Expected: salary 330000, recurring 25500, total 355500.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_income.py`
- C2 [review] `tests/cashflow/test_income.py` has the worked example. It also has: a quarterly income series counted as amount / 3 with half-up rounding on the total; a credit exactly 7 days from payday counted and one 8 days away not; a salary at payday − 2 counted in that payday's cycle; and None with recurring income but no salary credits (D3).
- C3 [review] `income.py` is pure (no sqlite, no `date.today`), reuses `SALARY_DAY_DISTANCE`, `detect_income` and `payday.complete_cycles` instead of copying them, uses integer cents and type hints, and adds no other public name than `ExpectedIncome` and `expected_income`.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 fixed costs per pay cycle
Do: Add `payday.next_cycles(today, salary_day, count)`: the cycles after the current one, oldest first and contiguous. Add `CycleCost` and a pure `forecast.cycle_costs(sources, rows, category_types, salary_day, estimate_date) -> tuple[CycleCost, ...]`: 13 cycles oldest first. Add `cycles: tuple[CycleCost, ...] = ()` to `FixedCosts`, leaving `months` in place for now (N06 removes it).
Context: D5: 6 `actual` cycles from `complete_cycles` (`src/sonar/cashflow/payday.py:82`, reversed to oldest first), then the `current` cycle from `current_cycle(estimate_date, …)` (`:75`), then 6 `forecast` cycles from `next_cycles`.
  D6: booked = the sum of |amount| of debits in `fixed`-group categories (`groups.FIXED`) inside the cycle; for the current cycle only up to and including the estimate date. Credits and other groups are ignored.
  D7: forecast = `fixed_due(sources, estimate_date + 1, last forecast cycle end)` (`src/sonar/cashflow/forecast.py:62`) bucketed by cycle; actual cycles have forecast 0 and forecast cycles have booked 0.
  D9: `CycleCost(start, end, kind: Literal["actual", "current", "forecast"], booked_cents, forecast_cents)`, both ≥ 0, with a `total_cents` property. `Row` is `sonar.recurring.detect.Row`.
Read: `src/sonar/cashflow/forecast.py`, `src/sonar/cashflow/payday.py`, `tests/cashflow/test_forecast.py:1-60`, `tests/cashflow/test_payday.py`
Write: `src/sonar/cashflow/forecast.py`, `src/sonar/cashflow/payday.py`, `tests/cashflow/test_forecast.py`, `tests/cashflow/test_payday.py`
Test first: The worked example uses salary day 25 and estimate date 2026-10-07. Sources: Rent 100000 monthly on day 1 (last paid 2026-10-01); Insurance 45000 every 3 months on day 15 from 2026-01-15 (last paid 2026-07-15); Phone 5000 monthly on day 10 until 2026-11-30 (last paid 2026-09-10). Rows: fixed debits −100000 on 2026-09-01, −5000 on 2026-09-10 and −100000 on 2026-10-01; a lights_on debit −8000 on 2026-09-05; a fixed credit +2000 on 2026-09-20.
  Expected: cycle 2026-08-25–09-24 is actual with booked 105000. The current cycle 2026-09-25–10-22 has booked 100000 and forecast 50000. The forecast cycles total 105000 (10-23–11-24), 100000 (11-25–12-24), 145000 (12-25–2027-01-24), 100000, 100000 and 145000 (2027-03-25–04-22). The 5 older actual cycles are 0.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_forecast.py tests/cashflow/test_payday.py`
- C2 [review] `test_forecast.py` holds the worked example (all 13 starts, ends, kinds and amounts) plus a case where a payment booked 2 days early in the current cycle is not forecast again. `test_payday.py` shows `next_cycles` contiguous with `current_cycle`, including a weekend-moved payday.
- C3 [review] `cycle_costs` is pure, takes the estimate date as a parameter, reuses `fixed_due` and the `payday` cycle functions, and uses integer cents. Every existing `fixed_costs` test passes unchanged.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 dashboard and API wiring
Do: Wire both pure pieces into `load_dashboard`. `Dashboard` gains `expected_income: ExpectedIncome | None`, set in the forecast branch when salary day and balance are both set and None otherwise. `fixed_costs` gets its `cycles` from `forecast.cycle_costs` when the salary day is set, else `()`. `/api/dashboard` then carries both through `_jsonable` without route changes.
Context: D5: the estimate date is `estimate_date` (`src/sonar/cashflow/service.py:125`); the sources are the existing `sources` (`:128`); the rows are `rows` (`:126`); the group map is `category_types`. Use `dataclasses.replace(forecast.fixed_costs(...), cycles=...)` or an equivalent one-liner; do not compute cycles twice.
  D8: no salary day → `cycles == ()`. D3: `expected_income` None when the pure function says so.
  D9: JSON gets `expected_income` (`{salary_cents, recurring_cents, total_cents}` or null) and `fixed_costs.cycles` (`{start, end, kind, booked_cents, forecast_cents}` with ISO dates); `fixed_costs.months` stays until N06. `_jsonable` is `src/sonar/web/api/_common.py:52`.
Read: `src/sonar/cashflow/service.py:39-195`, `src/sonar/cashflow/income.py`, `src/sonar/cashflow/forecast.py`, `tests/cashflow/test_service.py:1-170`, `tests/web/test_api_dashboard.py`
Write: `src/sonar/cashflow/service.py`, `tests/cashflow/test_service.py`, `tests/web/test_api_dashboard.py`
Test first: A service test with salary day 25, a balance on 2026-10-07, salary credits in an income category, and a fixed recurring payment. `board.expected_income.salary_cents` is the best cycle's salary, and `board.fixed_costs.cycles` has 13 entries with kinds 6× actual, current, 6× forecast and the current one starting 2026-09-25.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_service.py tests/web/test_api_dashboard.py`
- C2 [review] Service tests also show that without a salary day `fixed_costs.cycles == ()` and `expected_income is None`, and that without income credits `expected_income is None`.
- C3 [review] The API test asserts that `/api/dashboard` returns `expected_income` with the three cents fields and `fixed_costs.cycles` with 13 objects holding the five keys, equal to `load_dashboard`. A test without a salary day shows `expected_income` null and `cycles` [].
- C4 [review] `service.py` stays thin: no salary or cycle math of its own, only calls to `income.expected_income` and `forecast.cycle_costs`.
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 runway to income
Do: Extend the runway so its right end is the expected monthly income when there is one (D4), and draw the balance→income stretch, its scale mark, legend item and accessible text. Without income the bar stays exactly as today. Rebuild `sonar.css`.
Context: D4: `charts.runway` and `runway_scale` (`src/sonar/web/charts.py:29`, `:62`) take an optional `income: int | None = None`. The right end is max(0, balance, worst, best, income); `Runway` gains `income_x` (None without income). The scale adds an `income` mark (equal values share a label as today). `max_rows` may reach 4, so the macro's row height and top lists (`src/sonar/web/templates/components/charts.html:43`, `:47`) gain a 4th entry.
  `runway_bar(limit, balance, worst, best, income=None)` (`charts.html:4`) draws `data-part="to-income"` from balance_x to income_x only when income > balance. It sits over the zones, before the band and markers, in violet (`fill-violet-300 dark:fill-violet-800`), with `data-cents` = income and a `<title>`. The zones still tile [0, 300] (`tests/web/test_charts.py:200`). The aria-label and title gain ", expected monthly income X".
  `src/sonar/web/templates/index.html:92-99`: pass `dashboard.expected_income.total_cents` when present. Add `<li data-legend="income">` with a violet swatch: "Expected monthly income X (salary Y + recurring Z)", or without the brackets when recurring is 0. Amounts use `amount(..., colored=false)` as the other items.
  D3: expected_income None → no income argument, no legend item.
Read: `src/sonar/web/charts.py:20-112`, `src/sonar/web/templates/components/charts.html:1-52`, `src/sonar/web/templates/index.html:80-100`, `tests/web/test_charts.py:1-240`, `tests/web/test_dashboard_page.py:100-200`, `tests/html.py`
Write: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/templates/index.html`, `tests/web/test_charts.py`, `tests/web/test_dashboard_page.py`, `src/sonar/web/static/sonar.css`
Test first: `runway(-50000, -30000, -60000, 20000, 300, income=400000)` puts the right end at 400000, so the balance sits left of the middle and `income_x == 300`. Without income the old results are unchanged.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_charts.py tests/web/test_dashboard_page.py`
- C2 [review] Chart tests cover: a balance above the income ends the axis at the balance with no `to-income` rect; the `income` scale mark and its label; zones still contiguous with income; the aria-label naming the income. All existing runway tests pass unchanged.
- C3 [review] A page test with salary credits shows `#runway [data-legend=income]` with the total and `#runway [data-part=to-income]` with `data-cents` = the expected income. A page test without income credits has neither.
- C4 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && grep -q 'fill-violet-300' src/sonar/web/static/sonar.css`
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 pay-cycle chart and table
Do: Replace the 12-month column chart and table on the Fixed costs card with the pay-cycle chart and table (D10, D11), and the no-salary-day hint (D8). Remove `FixedCosts.months` from the public shape and from JSON (D9), and delete code left unused. Rebuild `sonar.css`.
Context: D10: a new macro `cycle_columns(cycles, estimate_date)` replaces `month_columns` (`src/sonar/web/templates/components/charts.html:54`). Heights come from `charts.columns` over `total_cents`, and the booked and forecast parts split each column by the same scale, computed in `charts.py`, not Jinja. Booked parts use `fill-sky-500 dark:fill-sky-400` with `data-part="booked"`. Forecast parts use `fill-amber-500/60 dark:fill-amber-400/60` with `data-part="forecast"`. Each rect has `data-cents` and a `<title>` with the range and amount. Each column group has `data-kind`.
  The current column has a `data-part="estimate"` marker labelled with the short estimate date and titled "Booked up to <date>, forecast after". Axis labels come from a pure `charts.cycle_label(start, end)` → "25 Sep – 24 Oct" and are rotated. The aria-label says 6 past, current and 6 next pay cycles. An HTML legend under the SVG has `data-legend` actual, forecast and estimate.
  D11: `<details>` summary "Pay-cycle totals as table", `<table id="cycles">` with Cycle, Type (Actual, Current, Forecast), Booked, Forecast and Total, each a `data-field`, amounts via `amount(..., colored=false)`. The chart wrapper id becomes `cycle-columns`.
  D8: cycles empty with no salary day → `<p id="cycles-hint">` linking to `/settings`.
  D9: `FixedCosts` keeps `monthly_equivalent_cents`, `rows` and `cycles` only. The 12-month basis of the Monthly equivalent (`src/sonar/cashflow/forecast.py:107-141`) stays as a private helper with unchanged results. `cycles` loses its default. Delete `MonthTotal`, `month_columns` and `charts.month_label` if unused, with their tests. Update `tests/test_real_sample.py:139` to 13 cycles.
Read: `src/sonar/web/templates/components/charts.html`, `src/sonar/web/templates/index.html:205-260`, `src/sonar/web/charts.py:145-215`, `src/sonar/cashflow/forecast.py`, `tests/web/test_charts.py:120-300`, `tests/web/test_dashboard_page.py:340-380`, `tests/cashflow/test_forecast.py`, `tests/html.py`
Write: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/templates/index.html`, `src/sonar/cashflow/forecast.py`, `tests/web/test_charts.py`, `tests/web/test_dashboard_page.py`, `tests/cashflow/test_forecast.py`, `tests/web/test_api_dashboard.py`, `tests/test_real_sample.py`, `src/sonar/web/static/sonar.css`
Test first: `cycle_label(date(2026, 9, 25), date(2026, 10, 24)) == "25 Sep – 24 Oct"`. The page test reads `#cycles` through `records` and gets 13 rows whose Type runs Actual ×6, Current, Forecast ×6.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_charts.py tests/web/test_dashboard_page.py tests/cashflow/test_forecast.py tests/web/test_api_dashboard.py`
- C2 [review] Macro tests: 13 `data-kind` groups. The current group has one booked and one forecast rect, stacked, whose heights sum to the column height. Actual groups have no forecast rect and forecast groups no booked rect. There is one `estimate` marker, and the legend items are present.
- C3 [review] Page tests: `#cycles` rows have the Booked, Forecast and Total of the fixture; `#cycle-columns` is present with a salary day; `#cycles-hint` links to `/settings` without one; `#monthly-equivalent` is unchanged. The API test asserts that `fixed_costs` has no `months` key.
- C4 [cmd] `! grep -rnE "MonthTotal|month_columns|fixed_costs\.months|#months" src tests --include=*.py --include=*.html`
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && grep -q 'fill-amber-500\\/60' src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 SPEC amendment
Do: Append one §13 bullet "Dashboard income runway and pay-cycle fixed costs (§9, §11, §12)" after the Payoff ladder bullet (`SPEC.md:255`). It states D1-D11 in plain words and changes no other line of SPEC.
Context: D1 the salary rule per complete cycle and its max over 3; D2 the recurring monthly equivalent; D3 the no-salary fallback; D4 the runway's right end, the balance→income segment, the scale mark and the legend.
  D5-D7: 13 pay-cycle columns from the estimate date: 6 actual fixed debits, the current cycle booked to the estimate date plus forecast, and 6 forecast cycles of every fixed row due, debts until their end.
  D8: no salary day → a settings hint. D10/D11: the chart look and the table columns. D9: `/api/dashboard` `expected_income` and `fixed_costs.cycles` replace `fixed_costs.months`.
  Say it overrides §9's "per-month totals for the next 12 months", §11's "the next 12 months per month" and §12's "12-month SVG column chart" and "spanning overdraft limit, 0 and balance". The Monthly equivalent is unchanged. Use the style of the existing §13 bullets (`SPEC.md:249`): one paragraph, no real names.
Read: `SPEC.md:118-148`, `SPEC.md:170-205`, `SPEC.md:240-255`
Write: `SPEC.md`
Test first: -
Done when:
- C1 [cmd] `git diff --numstat SPEC.md | awk '{exit !($1>=1 && $2==0)}' && grep -q "pay-cycle" SPEC.md`
- C2 [review] The new bullet covers every Decision D1-D11 listed above and names each overridden §9, §11 and §12 clause; no other SPEC line changed.
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 visual check of the dashboard
Do: Check `/` in the browser pane at desktop and 375px, light and dark, following the config `visual_recipe` on a temp DB. Use the newest sample, salary day 26 and a balance dated at the sample's last booking.
Context: Check twice: once with a positive balance below the expected income, then with a negative balance above the overdraft limit (`POST /api/settings/balance`). Also open `/` on a second fresh temp DB with no salary day for the D8 hint. Write no real figure into a tracked file.
  D4: the bar's right end is the expected monthly income (or the balance when higher) and the balance→income stretch is violet. D10/D11: 13 pay-cycle columns, actual solid sky, forecast translucent amber, the current one stacked with an estimate marker, rotated range labels, a legend and the table.
  Defects go back as a replan to N05 (runway), N06 (cycle chart, table, hint) or N04 (figures).
Done when:
- C1 [visual] Desktop 1280px, light and dark, positive balance: the runway runs from the overdraft limit to the expected income. The violet stretch starts at the balance marker and the legend item "Expected monthly income …" matches its swatch. Scale labels do not overlap.
- C2 [visual] Negative balance: the bar keeps its length (the right end is still the income). The balance marker sits in the overdraft zone, the violet stretch runs from it to the right end, and the projected band stays visible.
- C3 [visual] The Fixed costs card shows 13 columns: 6 solid sky, the current one sky under translucent amber with an estimate-date marker above it, and 6 translucent amber. The rotated "25 Sep – 24 Oct"-style labels are readable and unclipped, and the legend names Actual, Forecast and the estimate date. "Pay-cycle totals as table" opens a table with Cycle, Type, Booked, Forecast and Total. The Monthly equivalent stat is present.
- C4 [visual] 375px, light and dark: no page-level horizontal scroll, the runway labels and legend wrap without overlap, and every cycle column and label fits inside the card. The table fits or scrolls inside its wrapper.
- C5 [visual] The fresh DB with no salary day shows the Fixed costs card without a chart and with the hint linking to `/settings`.

## N09 plan acceptance
Do: Check the whole plan against its Definition of done, SPEC §11 and §12 as amended, and the AGENTS.md rules.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [review] SPEC §11 holds as amended. The dashboard shows due payments, the lights-on range, the payday projection and the traffic light unchanged. The Fixed costs section shows the monthly equivalent, the rows and the pay-cycle columns. SPEC §12 UI acceptance holds: `index.html` and `components/charts.html` have no inline `<style>`, amounts use `eur`/`amount`, dates use `date`, charts are inline SVG with `<title>` and aria-labels, and page tests use `tests/html.py` hooks.
- C4 [review] Per `git diff --stat` since N01: no new migration, no new `/api` route, no AGENTS.md change, and no Payoff or lights-on logic change. `income.py` and `cycle_costs` are pure with the estimate date as a parameter, and `tests/test_architecture.py` passes. Fixtures hold no real names, IBANs or ids.
- C5 [smoke] Start `uv run python -c` with `create_app` on a temp DB under `$TMPDIR`. `curl -s http://127.0.0.1:8000/api/dashboard` returns JSON with `expected_income` null and `fixed_costs.cycles` [] and no `months` key. `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/` prints 200. Stop the app.

## Log

### N01 try 1 · 2026-10-07
check: FAIL C4
- C4 exit 1: ls: cannot access 'samples/': No such file or directory

### N01 replan 1 · 2026-10-07
plan: ASK D13
- C4 failed: samples/ is absent (gitignored); AGENTS.md makes an empty samples/ a human checkpoint
- Added D13 proposed: owner supplies an export of at least 7 months (recommended) or N08 uses a synthetic one in TMPDIR; brief unchanged until answered
plan: REPLANNED
- D13 confirmed: owner copied a Deutsche Bank export (2026-01-01 to 2026-10-07, ~9 months) into samples/
- Brief unchanged; C4 now passes, N08 uses that sample

### N01 try 1 · 2026-10-07
check: PASS 4/4

### N02 try 1 · 2026-10-07
exec: DONE · 1279 passed
- Added cashflow/income.py: ExpectedIncome, expected_income (best salary of 3 complete cycles by payday distance + recurring monthly equivalent, None without salary)
- Recurring: yearly sum amount*12//interval, one half-up rounding on total/12

### N03 try 1 · 2026-10-07
exec: DONE · 1282 passed
- payday.next_cycles; forecast.CycleCost, cycle_costs (6 actual, current, 6 forecast), FixedCosts.cycles default ()
- booked = fixed-group debits; current cycle capped at estimate date; forecast via fixed_due from estimate+1

### N02 try 1 · 2026-10-07
check: PASS 2/2

### N03 try 1 · 2026-10-07
check: PASS 2/2
verify: PASS

### N02 try 1 · 2026-10-07
verify: FAIL C3
- C3 src/sonar/cashflow/income.py:23-24 - public module constants CYCLES_LOOKED_AT and MONTHS_PER_YEAR are added besides ExpectedIncome and expected_income - expected no other public name (underscore-private or inlined)

### N02 try 2 · 2026-10-07
exec: DONE · 1282 passed
- income.py: made CYCLES_LOOKED_AT and MONTHS_PER_YEAR underscore-private (C3 finding)
check: PASS 2/2
verify: PASS

### N04 try 1 · 2026-10-07
exec: DONE · 1287 passed
- Dashboard.expected_income (forecast branch only) and fixed_costs.cycles (when salary day set) wired in service.py via income.expected_income and forecast.cycle_costs
- cycles built once in _fixed_costs helper using replace(); API carries both via _jsonable unchanged
check: PASS 2/2
verify: FAIL C3
- C3 tests/web/test_api_dashboard.py:140-146 - cycles are only checked for length, key set, one 'current' count and cycles[6].start; end, kind, booked_cents and forecast_cents are never compared with load_dashboard's cycles - expected the API cycles asserted equal to board.fixed_costs.cycles

### N04 try 2 · 2026-10-07
exec: DONE · 1287 passed
- API test now asserts all 13 cycles equal load_dashboard's (start,end,kind,booked_cents,forecast_cents)
- fixed C3 finding; no source change
check: PASS 2/2
verify: PASS
