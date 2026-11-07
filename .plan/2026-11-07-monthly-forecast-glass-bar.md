# Monthly forecast ledger and glass bar
status: RUNNING
created: 2026-11-07 · updated: 2026-11-07
goal: /monthly explains income against spending as a top-down ledger, the current month adds what is still to come, and the income bar reads as a transparent glass tube
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The owner reads one month on /monthly without doing sums: what came in, what the fixed and keep-the-lights-on
payments took, what was left for occasional spending, and what really remained. In the running month the figures
count what is still expected until the period ends, so the residual stays about the same as the days pass instead
of looking better early in the month. The income bar shows the same story as a glossy glass tube whose fluid parts
are see-through and whose expected parts are clearly marked.

In scope: a pure ledger over a month's paid totals plus an optional upcoming part (cashflow/monthly.py); the
current period's upcoming fixed payments, keep-the-lights-on spending and recurring income, taken from the
dashboard's existing forecast pieces in cashflow/service.py; income bar geometry with paid and upcoming segments
(web/charts.py); the glass look in the bar macro and a small app.css rule; the stats grid replaced by a ledger plus
a separate "not counted" area on monthly.html; a SPEC §13 amendment; the rebuilt sonar.css.

Out of scope: other pages and their numbers (the dashboard stays exactly as it is), /api/monthly, the category
table and payment list (paid only), the group filter rules, any new forecasting method, forecasting occasional or
uncategorized spending, forecasts for past or future months.

Constraints: AGENTS.md rules: strict TDD, pure core with the estimate date as a parameter, integer cents, store and
service layering, page parts as `components/` macros, page tests through `tests/html.py` hooks, no inline `<style>`,
colours as theme tokens in light and dark, rebuild and commit sonar.css after template or CSS changes. Group names
come from `sonar.categorization.groups` constants, never string literals. Decisions D1-D15 below.

Definition of done: verify passes; in the current period each forecast line shows paid + upcoming, and booking an
expected payment moves cents from upcoming to paid without changing the line total or the residual; past months
show paid figures only; the glass bar visibly shows the zone tint through the fluid in light and dark at desktop
and 375px; the ledger reads Net income − Fixed − Keep the lights on = Possible residual − Occasional = Actual
residual.

## Decisions

- D1 Current period and window: the period (salary or calendar month) that holds the estimate date, the balance's as-of date as on the dashboard; upcoming covers estimate date + 1 .. period end; no upcoming without a salary day and a balance, or when that window is empty | confirmed
- D2 Fixed upcoming: the dashboard's due list for that window (recurring payments and debt schedules via `forecast.fixed_due`, utility settlement payments, meter advances), its code extracted from `load_dashboard` into a helper both use; dashboard numbers unchanged | confirmed
- D3 Keep-the-lights-on upcoming: `lights_on.lights_on_forecast(months, window_days).expected_cents` over the dashboard's months (`last_known_day` + `month_spends`); none when "not enough data" | confirmed
- D4 Income upcoming: recurring income series still due in the window (service.py `_inflows`, named by category); utility settlement refunds are not income | confirmed
- D5 Occasional and uncategorized spending are never forecast; past and future months have no upcoming part | confirmed
- D6 Wording: in a month with upcoming, every spending line, bar title and legend item says "paid" or "upcoming"; past months keep today's labels | confirmed
- D7 Bar segments: per group a paid segment (group colour at 60% opacity) then an upcoming segment (same colour at 30% opacity, diagonal hatch, dashed leading edge); order fixed paid, fixed upcoming, lights_on paid, lights_on upcoming, occasional, uncategorized, residual; the existing cumulative width rule on that list; income at 70% is paid + upcoming | confirmed
- D8 Glass tube: one `@layer components` block in app.css (`glass-tube`, `glass-fluid`, `glass-upcoming`): rounded-full ends, inset shadow, top specular highlight; zones as tinted glass (`positive`/`negative` at about 20%); new tokens `--color-glass-shine` and `--color-glass-shade` with dark values | confirmed
- D9 Ledger layout: one column read top-down with an operator column (−, =): Net income with its per-category breakdown, − Fixed payments, − Keep the lights on, = Possible residual income, − Occasional payments, − Uncategorized when not zero, = Actual residual income; subtotal rows bold over a rule; current month adds a muted "X paid + Y upcoming" under each forecast line; below it "Spent X = A Fixed + B Keep the lights on + C Occasional [+ D Uncategorized]"; then a muted, bordered "For information, not counted" area with the transfers stat and the payments count; a new `components/ledger.html` macro | confirmed
- D10 Signs: ledger lines show uncoloured magnitudes after their operator; the two residual lines are signed and coloured; every `data-cents` stays signed (spending negative, as `#group-fixed` today) | confirmed
- D11 Spent (`#month-total`) in the current month is paid + upcoming, with `data-upcoming-cents` | confirmed
- D12 With zero income (paid + upcoming), the ledger omits Net income and both residual lines and the bar is absent, as today | confirmed
- D13 Category table, payment list, group filter and /api/monthly stay paid only and unchanged | confirmed
- D14 A SPEC §13 amendment "Monthly ledger and forecast (§9, §12)" records these rules and overrides the Monthly income bar bullet's zone colours, segment list and stat layout | confirmed
- D15 Visual gate on a temp DB, pre-authorized: import the newest sample; salary day 26 and a balance as of the last booking for past months; then salary day 10 with the same balance so the current period has about two weeks upcoming | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/haiku | 1 | 0 | DONE | |
| N02 | SPEC amendment | exec | N01 | gpt-6.1-sol@low/sonnet | 1 | 0 | DONE | |
| N03 | ledger core | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N04 | current period forecast | exec | N03 | gpt-6.1-sol@high/sonnet | 1 | 0 | DONE | |
| N05 | glass income bar | exec | N04 | gpt-6.1-sol@high/sonnet | 0 | 0 | TODO | |
| N06 | ledger page | exec | N05 | gpt-6.1-sol@medium/sonnet | 0 | 0 | TODO | |
| N07 | visual check | gate | N02,N06 | -/sonnet | 0 | 0 | TODO | |
| N08 | plan acceptance | check | N07 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point: verify passes on the untouched tree, the CSS build tool runs (it may download its
  binary), the sample the visual gate needs exists, and the repo is writable.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
- C3 [cmd] `ls samples/*.csv`
- C4 [cmd] `test -w .git && test -w src/sonar/web/static/sonar.css`

## N02 SPEC amendment
Do: Append one SPEC §13 bullet "Monthly ledger and forecast (§9, §12)" after the last bullet of SPEC.md (line 278),
  overriding in the Monthly income bar bullet (SPEC.md:276) the zone colours, segment list and stat layout. It states:
  current period = the salary or calendar month holding the balance's as-of date; upcoming covers the next day to
  the period end; none without salary day and balance or with an empty window; past and future months none.
  Fixed upcoming = the dashboard's due items for that window (recurring, debt schedules, utility settlement
  payments, meter advances); Keep the lights on upcoming = the dashboard's lights-on expected for the window's days;
  income upcoming = recurring income series due in the window, by category, refunds excluded; occasional and
  uncategorized never forecast. Ledger, top-down: Net income (per income category, "4.500 € Salary + 500 € Child
  Allowance" style) − Fixed payments − Keep the lights on = Possible residual income − Occasional payments
  − Uncategorized (when not zero) = Actual residual income (negative when overspent); spending lines are magnitudes
  after their operator, residuals signed and coloured; in the current month each forecast line shows "X paid + Y
  upcoming"; Spent = paid + upcoming, shown as the sum of its parts; zero income omits Net income, both residuals
  and the bar. Transfers stat and Payments count sit in a separate "For information, not counted" area; group links
  stay. Bar: per group a paid segment (60% opacity) then an upcoming segment (30% opacity, hatched), order fixed,
  lights_on, occasional, uncategorized, residual; same cumulative width rule over paid + upcoming income; zones are
  tinted glass; glossy tube with rounded ends, highlight and inner shadow; titles and legend say paid or upcoming
  only in a month with upcoming. Hooks: `#monthly-ledger`, `#net-income`, `[data-part="income-category"]`,
  `#possible-residual`, `#residual-income` (actual), `#month-total`, `data-upcoming-cents`, `#not-counted`,
  `#forecast-note`, segment `data-kind` paid or upcoming. Category table, payment list, group filter and
  /api/monthly unchanged.
Context: SPEC.md:225 opens §13; style of SPEC.md:276-278. Docs only; no code.
Read: `SPEC.md`
Write: `SPEC.md`
Test first: -
Done when:
- C1 [review] SPEC.md ends with one new §13 bullet covering every rule listed in Do and naming what it overrides
- C2 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 ledger core
Do: Add the pure ledger to src/sonar/cashflow/monthly.py. `MonthlySpending` gains `income_by_category:
  tuple[tuple[str, int], ...]`: positive credits in income-group categories per category, largest first then name;
  `income_cents` equals their sum. New frozen dataclasses: `Upcoming(start, end, fixed_cents, lights_on_cents,
  income_by_category)` (spending negative cents like `GroupTotals`, income positive); `LedgerLine(name, paid_cents,
  upcoming_cents)` with `total_cents`; `Ledger(income, fixed, lights_on, occasional, uncategorized, upcoming)` where
  `income` is a tuple of LedgerLine per income category and `upcoming` is the `Upcoming` or None, with properties
  `income_cents`, `spent` (a LedgerLine of the four spending lines), `possible_residual_cents` (income + fixed +
  lights_on totals) and `actual_residual_cents` (possible + occasional + uncategorized). `ledger(spending,
  upcoming=None) -> Ledger` merges paid and upcoming income by category (total descending, then name); occasional
  and uncategorized never have upcoming cents.
Context: Spending cents are negative throughout (monthly.py:77-86, groups.py:50). Use `groups` constants for group
  keys, never literals. Pure functions only, no date.today().
Read: `src/sonar/cashflow/monthly.py`, `src/sonar/categorization/groups.py`, `tests/cashflow/test_monthly.py`
Write: `src/sonar/cashflow/monthly.py`, `tests/cashflow/test_monthly_ledger.py`
Test first: tests/cashflow/test_monthly_ledger.py: income per category from a period's credits; a ledger without
  upcoming equals the paid figures and today's `residual_cents`; with upcoming, lines sum paid + upcoming, income
  parts merge (a category only upcoming appears), and both residuals follow their formulas, negative when overspent.
Done when:
- C1 [review] `ledger` and the new dataclasses in monthly.py are pure, typed, integer-cent, and match the Do
- C2 [review] tests/cashflow/test_monthly_ledger.py covers each formula and the no-upcoming case
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 current period forecast
Do: In src/sonar/cashflow/service.py extract the dashboard's window forecast (service.py:194-219: due list,
  inflows, lights-on months and forecast) into private helpers that `load_dashboard` and `load_monthly` both call;
  dashboard results stay identical. `MonthlyView` gains `upcoming: Upcoming | None` and `ledger: Ledger`
  (`monthly.ledger(spending, upcoming)`). Rules: estimate date = balance as-of date; upcoming only with a salary day
  and a balance, when the selected period holds the estimate date and the window estimate date + 1 .. period end
  is not empty; fixed_cents = minus the due total for that window (recurring, debt schedules, utility settlement
  payments, meter advances, as the dashboard); lights_on_cents = minus `lights_on_forecast(months,
  window_days).expected_cents`, 0 when it is None; income_by_category = `_inflows` for the window summed per item
  name, settlement refunds excluded. src/sonar/web/pages/monthly.py adds `ledger` to the template context.
Context: load_monthly at service.py:352; dashboard window at service.py:184-219; `_inflows` at service.py:474.
  /api/monthly (web/api/cashflow.py:90) must not change. Pass the estimate date; never call date.today().
Read: `src/sonar/cashflow/service.py`, `src/sonar/cashflow/monthly.py`, `src/sonar/cashflow/lights_on.py`,
  `tests/cashflow/test_service.py`, `src/sonar/web/pages/monthly.py`
Write: `src/sonar/cashflow/service.py`, `src/sonar/web/pages/monthly.py`, `tests/cashflow/test_service_monthly_upcoming.py`
Test first: tests/cashflow/test_service_monthly_upcoming.py: with salary day and a balance inside the selected period,
  upcoming holds the fixed payment still due, lights-on daily expected × window days and a recurring income due in
  the window by category; a past month, no balance, or no salary day give None; stability: importing the expected
  fixed payment and moving the balance date past it keeps fixed paid + upcoming and the actual residual unchanged.
Done when:
- C1 [review] load_dashboard and load_monthly share the extracted helpers; no forecasting rule is duplicated or new
- C2 [review] the stability test exists and asserts equal fixed totals and residuals before and after the booking
- C3 [cmd] `uv run pytest -q -x tests/cashflow tests/web/test_api_dashboard.py tests/web/test_api_monthly.py`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 glass income bar
Do: `charts.income_bar(ledger)` (src/sonar/web/charts.py:216) takes a `Ledger`: segments in order fixed paid, fixed
  upcoming, lights_on paid, lights_on upcoming, occasional, uncategorized, residual (only when positive), zero
  ones skipped; `IncomeSegment` gains `upcoming: bool`; income = `ledger.income_cents`, spent = magnitude of all
  four lines incl. upcoming; the cumulative tenths width rule, 1000 cap and label tiers stay. The macro
  (components/charts.html:300) becomes `income_bar(ledger)`; monthly.html:88 calls it with the context `ledger`.
  Look: the tube is `glass-tube` (rounded-full, inner shadow, top specular highlight); zones tinted
  `bg-positive/20` and `bg-negative/20`; paid fluid at 60% of the group colour (`bg-fixed/60` etc.), upcoming
  at 30% with class `glass-upcoming` (diagonal hatch, dashed leading edge). Add one `@layer components` block in
  src/sonar/web/static/src/app.css for `glass-tube`, `glass-fluid`, `glass-upcoming`, plus `--color-glass-shine`
  and `--color-glass-shade` in `@theme` and `.dark`. In a month with upcoming, titles, aria-labels and legend items
  read "<full name> paid: X" / "<full name> upcoming: Y"; otherwise today's labels. Segments add `data-kind`
  ("paid" or "upcoming"). Rebuild sonar.css (AGENTS.md Setup).
Context: Keep every existing hook (charts.html:310-353, SPEC.md:276). Colours only via tokens; no inline `<style>`.
Read: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/static/src/app.css`,
  `tests/web/test_charts_income_bar.py`, `tests/web/test_monthly_income_bar.py`, `src/sonar/cashflow/monthly.py`
Write: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/templates/monthly.html`,
  `src/sonar/web/static/src/app.css`, `src/sonar/web/static/sonar.css`, `tests/web/test_charts_income_bar.py`,
  `tests/web/test_monthly_income_bar.py`
Test first: geometry tests build a Ledger and expect paid then upcoming segments with exact widths; markup test
  renders the macro with upcoming and finds `data-kind="upcoming"` segments, "paid"/"upcoming" titles and legend.
Done when:
- C1 [review] income_bar orders, skips and sizes segments as in Do; existing geometry cases still pass
- C2 [review] app.css has one `@layer components` block and the two tokens with dark values; no raw palette colours
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-n05.css" --minify && cmp "$TMPDIR/plz-n05.css" src/sonar/web/static/sonar.css`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 ledger page
Do: Replace the stats grid (src/sonar/web/templates/monthly.html:71-85) with a ledger built from the context
  `ledger`, using a new macro `ledger_line(label, cents, operator, id, href, current, upcoming_cents, attrs)` in
  src/sonar/web/templates/components/ledger.html. Rows, top-down in `#monthly-ledger`: Net income (`#net-income`)
  with its breakdown, one `[data-part="income-category"]` per category with `data-category`, `data-cents`,
  `data-upcoming-cents` ("4.500 € Salary + 500 € Child Allowance"); − Fixed payments (`#stat-fixed` link,
  `#group-fixed`); − Keep the lights on (`#stat-lights-on`, `#group-lights-on`); = Possible residual income
  (`#possible-residual`); − Occasional payments (`#stat-occasional`, `#group-occasional`); − Uncategorized
  (`#group-uncategorized`) only when not zero; = Actual residual income (`#residual-income`). Amounts carry line
  totals (paid + upcoming) as signed cents; spending shows uncoloured magnitudes after the operator, residuals
  signed and coloured; subtotals bold over a rule. With upcoming, each forecast line adds a muted "X paid + Y
  upcoming" and `data-upcoming-cents`, and `#forecast-note` names the window (`data-field="from"`/`"to"` dates).
  Below: "Spent X = A Fixed + B Keep the lights on + C Occasional [+ D Uncategorized]" (`#month-total` total,
  `data-upcoming-cents`). Then `<aside id="not-counted">` "For information, not counted", muted with a top border,
  holding `#stat-transfer`/`#transfers-net` and `#payments-count`. Zero income omits Net income and both residuals.
  Group links keep href, `aria-current` and boost (monthly.html:76-78). Rebuild sonar.css.
Read: `src/sonar/web/templates/monthly.html`, `src/sonar/web/templates/components/stat.html`,
  `src/sonar/web/templates/components/amount.html`, `tests/html.py`, `tests/web/test_monthly_page.py`,
  `tests/web/test_monthly_group_filter.py`, `src/sonar/cashflow/monthly.py`
Write: `src/sonar/web/templates/monthly.html`, `src/sonar/web/templates/components/ledger.html`,
  `src/sonar/web/static/sonar.css`, `tests/web/test_monthly_ledger.py`, `tests/web/test_monthly_page.py`
Test first: tests/web/test_monthly_ledger.py through tests/html.py: past month rows in order with values equal to
  the paid groups and both residual formulas; a current month (seed a salary day and a balance inside it) shows
  paid + upcoming and `data-upcoming-cents`; zero income omits the income and residual rows; not-counted holds the
  transfers stat and payments count; group links keep `aria-current`.
Done when:
- C1 [review] the ledger reads in the order of Do, every listed id and data hook exists, and no inline `<style>`
- C2 [review] the group filter tests pass unchanged; `#residual-income` now holds the actual residual
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-n06.css" --minify && cmp "$TMPDIR/plz-n06.css" src/sonar/web/static/sonar.css`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 visual check
Do: gate, pre-authorized. Run `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`,
  then start the app per config `visual_recipe` on `$TMPDIR/sonar-visual.db`; import the newest file in `samples/`
  on /import. Past months: on /settings set salary day 26 and a balance as of the sample's last booking date; via
  `GET /api/monthly?month=YYYY-MM` pick a month with a residual and one where spent exceeds income. Current month:
  set salary day 10 with the same balance so the period holding the balance date has about two weeks upcoming.
  Check /monthly for the past months and the current month at desktop and 375px, light and dark (read_page first,
  scaled screenshots only where layout matters); click each group line once. Stop the app.
Done when:
- C1 [visual] the ledger reads Net income (with category breakdown) − Fixed − Keep the lights on = Possible residual
  − Occasional = Actual residual; the arithmetic holds; actual residual is negative in the overspend month
- C2 [visual] the current month shows "paid + upcoming" under Fixed and Keep the lights on and a forecast note;
  past months show no upcoming parts
- C3 [visual] the bar looks like a glossy glass tube with rounded ends and highlight; the green and red zone tint
  shows through the fluid; upcoming segments are paler and hatched; legend and titles say paid and upcoming
- C4 [visual] the not-counted area is visually separate; each group line filters the payments and is marked active
- C5 [visual] at 375px nothing overflows the card or scrolls the page sideways; light and dark both readable

## N08 plan acceptance
Do: Whole-plan check: full verify, and the work against AGENTS.md rules and SPEC §11 (SPEC.md:162) and §12
  (SPEC.md:178) as amended by the new §13 bullet.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `uv run pytest -q tests/test_architecture.py tests/web/test_templates_hygiene.py tests/web/test_api_monthly.py tests/web/test_api_dashboard.py`
- C3 [review] domain code is pure with the estimate date as a parameter; money is integer cents; the forecast reuses
  the dashboard helpers with no new forecasting rule; new code sits in existing packages
- C4 [review] every Monthly behaviour in the new SPEC §13 bullet has a test; sonar.css matches a fresh build;
  SPEC §11 and §12 items touching Monthly and the dashboard still hold

## Log

### N01 try 1 · 2026-11-07
check: PASS 4/4

### N02 try 1 · 2026-11-07
exec: DONE · 2245 passed; ruff check clean
- Appended SPEC §13 Monthly ledger and forecast with forecast window, ledger, glass bar and hooks.
- Explicitly overrides Monthly income bar colours, segments and stat layout; API and filtering unchanged.

### N03 try 1 · 2026-11-07
exec: DONE · 2253 passed; ruff check clean; changed files formatted
- Added per-category income and pure frozen ledger types with paid, upcoming and residual totals.
- Used group constants and labels; eight tests cover category filtering, merging, sorting, totals and negative residuals.

### N02 try 1 · 2026-11-07
check: PASS 1/1

### N03 try 1 · 2026-11-07
check: PASS 1/1
verify: PASS

### N02 try 1 · 2026-11-07
verify: PASS

### N04 try 1 · 2026-11-07
exec: DONE · 2264 passed; ruff check and format clean
- Shared dashboard window forecasting with monthly upcoming and ledger; exposed ledger in page context.
- Balance-date window excludes settlement refunds from monthly income; tests cover booking stability, setup guards, and due sources.
check: PASS 2/2
verify: PASS
