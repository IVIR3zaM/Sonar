# Debt payoff ladder page
status: WAITING
created: 2026-10-06 · updated: 2026-10-06
goal: A /payoff page shows, step by step from the smallest open debt up, how much paying now would free of the monthly fixed payments.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: the owner sees what an early payoff buys. The open installments and loans are lined up from the smallest remaining amount to the largest. Each step adds the next debt, and the page shows the total to pay now and how much lower the monthly fixed payments get. Fixed payments are not all monthly, so each figure is a range from the cheapest month to the dearest of the next 12 months.

In scope: a pure ladder function in the debts package, with tests built on the worked example. A loader next to `load_dashboard` that feeds it the same 12-month fixed-cost series as the dashboard chart. Log-scale tick geometry in `web/charts.py`. A `/payoff` page with a "Payoff" nav entry after "Installments and loans". A step slider driven by one small vanilla JS file in `static/`. All steps are server-rendered, so they stay readable without JS. An empty state for when there are no open debts. A SPEC §13 amendment, a visual gate and a final check.

Out of scope: a JSON API endpoint (the AGENTS.md endpoint table stays unchanged), editing debts from this page, interest savings, prepayment penalties, migrations, and any change to the dashboard or Debts page output.

Constraints: AGENTS.md rules. Strict TDD, money in integer cents, and the estimate date is passed in, never `date.today()`. The routes go in `web/pages/payoff.py` and `app.py` only wires them. The page uses the `components/` macros with no inline `<style>`, the `eur` filter or `amount` macro for amounts, and the `date` macro for dates. Rebuild `sonar.css` after template changes. Page tests go through `tests/html.py` on ids and `data-*` hooks. Fixtures are anonymized. `tests/test_architecture.py` must pass. Decisions D1-D11.

Definition of done: the plan `verify` passes. `/payoff` works at desktop and 375px, light and dark, with the slider switching steps and no request. The empty state shows on a DB without debts. SPEC §13 has the amendment. The final check passes against SPEC §11 and §12.

## Decisions

- D1 Ladder membership: every debt from `debt_overview(conn, estimate_date)` whose status is not `paid_off` and whose `remaining_cents(view)` is above 0. The estimate date is the current balance's `as_of`, else `today`, as in `load_dashboard` (`src/sonar/cashflow/service.py:79`). Debts sort by remaining amount ascending, then by name, then by id | confirmed
- D2 Figures per step (from the request): pay now = the sum of the remaining amounts of the debts included so far. `before` is the 12 monthly totals of `forecast.fixed_costs(sources, estimate_date).months`, the dashboard's Fixed costs chart. `after[m] = before[m] −` the included debts' own payments in month m, each debt's payments coming from the same `FixedSource` the dashboard builds for it. The step reports `before`/`after` min and max over the 12 months, `freed_min = before_min − after_min` and `freed_max = before_max − after_max` | confirmed
- D3 Code placement: the pure `src/sonar/debts/payoff.py` (`LadderDebt`, `PayoffStep`, `payoff_ladder`) imports nothing from cashflow. The loader `load_payoff(conn, today) -> Payoff` sits in `src/sonar/cashflow/service.py` and reuses `_fixed_sources`. `forecast._month_totals` becomes the public `month_totals` | confirmed
- D4 Slider geometry: a native range input, `min=0 max=1000 step=1`. Each step sits at `position = round(percent * 10)`, where percent is `100 * (log10(pay_now) − log10(first)) / (log10(last) − log10(first))`, one decimal; a single step sits at 0. Tick labels are `compact_eur(pay_now)`, aligned like the runway scale and put into at most 3 rows by a greedy pass with `TICK_MIN_GAP = 12` percent. A tick that fits no row keeps its mark but has no label. The row pass is extracted from `runway_scale` and shared, which makes two real uses | confirmed
- D5 JS behavior: `static/payoff.js` snaps the slider to the nearest step on `input` and shows only that step's panel. Arrow keys and PageUp/PageDown move one step, and Home/End go to the first or last step. It sets `aria-valuetext` to the step's pay-now text. It toggles only the `hidden` attribute and `data-selected`, never classes, because Tailwind does not scan `static/`. It makes no network request. Step 1 is selected on load | confirmed
- D6 Without JS: the slider block carries `hidden` and JS removes it. Every step's panel is rendered without `hidden`, each listing its own included debts, so all steps read top to bottom | confirmed
- D7 Ranges display as "min – max", collapsing to one amount when min equals max. The wrapper always carries `data-min-cents` and `data-max-cents`. The fixed payments per month before any payoff appear once, as a stat `#payoff-fixed-now` above the slider | confirmed
- D8 Nav: `("/payoff", "Payoff", "payoff")` goes right after `/debts` in `nav_items` (`src/sonar/web/templates/base.html:17`), with a new `"payoff"` icon: a 24×24 stroke path in the same style as the others, for example a downward trend arrow | confirmed
- D9 Script loading: `payoff.html` ends its content block with `<script src="/static/payoff.js" defer></script>`, only when there are steps; `base.html` gets no new block. The SPEC §13 amendment records that this page's script file overrides §12's "small inline progressive-enhancement scripts only" | confirmed
- D10 SPEC: one §13 bullet, "Payoff ladder (§7, §9, §12)", stating D1, D2, D4-D7 and D9 in two or three sentences | confirmed
- D11 Pre-authorized mid-run actions: rebuild and commit `sonar.css`, and start the app on a temp DB for smoke and visual runs (config `preauthorized`). The gate adds anonymized debts to the temp DB through `POST /api/debts`. No other human stops are planned | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/haiku | 1 | 1 | DONE | |
| N02 | pure payoff ladder | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | log-scale tick geometry | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | payoff loader | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N05 | payoff page and nav | exec | N03,N04 | sonnet/sonnet | 1 | 0 | DONE | |
| N06 | step slider script | exec | N05 | sonnet/sonnet | 1 | 0 | DONE | |
| N07 | SPEC amendment | exec | N05 | haiku/sonnet | 1 | 0 | DONE | |
| N08 | visual check of payoff | gate | N06,N07 | -/sonnet | 0 | 0 | TODO | |
| N09 | plan acceptance | check | N08 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point before any work. The untouched tree passes verify, the Tailwind build runs, the repo is writable for the per-node commits, and `samples/` has a file for the visual gate.
Context: Tailwind's automatic source detection also scans untracked, non-ignored files such as `.plan/*.md`, so a build into `src/sonar/web/static/sonar.css` picks up class names from plan text and differs from HEAD. That is expected, not a failure. The preflight therefore builds into a temp file and never writes the tracked `sonar.css`. A stray rebuilt `sonar.css` in the working tree is generated output and is reset to HEAD first (pre-authorized; the file is never hand-edited, AGENTS.md).
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `git checkout -- src/sonar/web/static/sonar.css && TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "${TMPDIR:-/tmp}/sonar-preflight.css" --minify && test -s "${TMPDIR:-/tmp}/sonar-preflight.css" && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [cmd] `test -w .git && git rev-parse --abbrev-ref HEAD`
- C4 [cmd] `test -n "$(ls samples/)"`

## N02 pure payoff ladder
Do: Add `src/sonar/debts/payoff.py`, a pure module that builds the cumulative payoff steps from plain data. It imports nothing from `sonar.cashflow` and nothing from a store.
Context: Types, frozen dataclasses:
  - `LadderDebt`: `id: int`, `kind: Literal["installment", "loan"]`, `name: str`, `remaining_cents: int`, `rate_cents: int`, `interval_months: int`, `end_date: date | None`, and `months: tuple[int, ...]`, which is this debt's own fixed payments per month, aligned with the base series.
  - `PayoffStep`: `number` (1-based), `pay_now_cents`, `debts: tuple[LadderDebt, ...]` (the included debts, in ladder order), `before_min_cents`, `before_max_cents`, `after_min_cents`, `after_max_cents`, `freed_min_cents`, `freed_max_cents`.
  `payoff_ladder(debts: Sequence[LadderDebt], fixed_months: Sequence[int]) -> tuple[PayoffStep, ...]`:
  - D1: drop debts with `remaining_cents <= 0`, then sort by `(remaining_cents, name, id)`.
  - D2: step k includes the first k debts. `pay_now` is the sum of their remaining amounts. `after[m] = fixed_months[m] − sum(d.months[m])` over the included debts. min and max are taken over the months. `freed_min = before_min − after_min` and `freed_max = before_max − after_max`.
  - A debt whose `months` length differs from `fixed_months` raises `ValueError`. No debts gives `()`.
  A module docstring says why the range exists: fixed payments are not all monthly.
Read: `src/sonar/debts/model.py:45-100`, `tests/debts/test_model.py:1-40`
Write: `src/sonar/debts/payoff.py`, `tests/debts/test_payoff.py`
Test first: the worked example, in cents, with the debts passed in shuffled order. The fixed series is 300000 in each of 12 months. TV: remaining 30000, months all 4000. Car: 1800000, all 70000. Mortgage: 12000000, all 150000. Expected: step 1 pays 30000, frees 4000, fixed after 296000. Step 2 pays 1830000, frees 74000, fixed after 226000. Step 3 pays 13830000, frees 224000, fixed after 76000. min equals max in every step, and the steps name TV, then car, then mortgage. It fails because the module does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts/test_payoff.py`
- C2 [review] `tests/debts/test_payoff.py` covers the worked example and a quarterly debt over an uneven base, where min and max differ and freed min and max follow D2's formulas, not per-month differences. It also covers a zero-remaining debt left out, a remaining-amount tie ordered by name, the length-mismatch `ValueError`, and no debts giving `()`.
- C3 [review] `payoff.py` has type hints, uses only integer cents, never calls `date.today()`, and imports no `sqlite3`, `sonar.cashflow` or store module.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 log-scale tick geometry
Do: Add `payoff_ticks(amounts: Sequence[int]) -> list[PayoffTick]` to `src/sonar/web/charts.py`. It gives the slider's tick positions on a log scale of the cumulative pay-now amounts, plus label rows that never overlap.
Context: D4. `PayoffTick` is a frozen dataclass with `cents`, `percent` (float, one decimal), `position` (`round(percent * 10)`, 0-1000, the range input's value), `align` (from `_align`, `charts.py:93`) and `row` (`int | None`). The amounts come in ascending order and are all positive.
  percent is `100 * (log10(a) − log10(first)) / (log10(last) − log10(first))`. A single amount gets 0.0, and an empty input gives `[]`.
  Rows: extract the greedy pass of `runway_scale` (`charts.py:78-90`) into a private helper taking the percents, a min gap and a max row count. `runway_scale` keeps `SCALE_MIN_GAP` and no row limit, and its output stays the same. `payoff_ticks` uses `TICK_MIN_GAP = 12` and at most 3 rows. A tick with no free row gets `row=None`.
  A comment says why the scale is log: one large mortgage would otherwise crowd every small debt into the left edge, and why the gap is 12: a label like "138k €" at text-xs is about 12% of a 375px slider.
Read: `src/sonar/web/charts.py`, `tests/web/test_charts.py:1-40`
Write: `src/sonar/web/charts.py`, `tests/web/test_charts.py`
Test first: `payoff_ticks([30000, 1830000, 13830000])` gives percents `[0.0, 67.0, 100.0]`, positions `[0, 670, 1000]`, aligns `["start", "center", "end"]` and rows `[0, 0, 0]`. It fails because the function does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_charts.py`
- C2 [review] Tests cover the Test first case, a single amount at 0.0 and position 0, `[]` for no amounts, close amounts landing on different rows, and a fourth crowded tick getting `row=None`.
- C3 [review] The existing `runway_scale` tests pass with their assertions unchanged (`git diff tests/web/test_charts.py` only adds tests). One helper serves both functions, so there are not two copies of the greedy loop.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 payoff loader
Do: Add `load_payoff(conn, today) -> Payoff` to `src/sonar/cashflow/service.py`. It feeds `payoff_ladder` (`src/sonar/debts/payoff.py`, N02) the dashboard's own fixed-cost series and each open debt's own monthly payments.
Context: `Payoff` is a frozen dataclass with `estimate_date: date`, `steps: tuple[PayoffStep, ...]` and `before_min_cents`/`before_max_cents` (the base series' min and max, kept for the page even when there are no steps).
  D1: `estimate_date` is the current balance's `as_of`, else `today`, as at `service.py:79-81`. Use `debt_overview(conn, estimate_date)` and keep only views whose status is not `paid_off`.
  D2/D3: in `src/sonar/cashflow/forecast.py`, rename `_month_totals` (`:120`) to the public `month_totals`, and change the call at `:108` to match. The base is `[m.total_cents for m in month_totals(sources, estimate_date)]`, where sources come from `_fixed_sources` (`service.py:233`).
  Extract `_debt_source(view, txs) -> FixedSource` from the `owed` list there and use it in both places. Each debt's `months` comes from `month_totals((_debt_source(view, txs),), estimate_date)`, so a payment is counted exactly as on the dashboard chart.
  LadderDebt fields: `kind` comes from `isinstance(view.debt, Installment)` and `remaining_cents` from `remaining_cents(view)`. `interval_months` is the debt's own for an installment and 1 for a loan. `end_date` is `status.end_date` for an installment and `status.payoff_date` for a loan (it may be None).
Read: `src/sonar/cashflow/service.py:1-110` and `:225-260`, `src/sonar/cashflow/forecast.py:100-131`, `src/sonar/debts/payoff.py`, `src/sonar/debts/store.py:40-100`, `tests/cashflow/test_service.py:1-130`
Write: `src/sonar/cashflow/service.py`, `src/sonar/cashflow/forecast.py`, `tests/cashflow/test_service.py`
Test first: in `tests/cashflow/test_service.py`, with the helpers at `:35-130`, seed a monthly recurring payment and an installment that pays in each of the next 12 months. `load_payoff` then gives one step. Its `before` min and max equal the min and max of `load_dashboard(conn, {}, TODAY).fixed_costs.months` totals, and it frees exactly the installment's rate. It fails because `load_payoff` does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow`
- C2 [review] Tests cover these cases. A paid-off installment is left off the ladder. The estimate date follows the balance `as_of` (a loan's remaining amount is its projected balance at that date). A recurring payment linked to a debt is counted once: paying that debt off removes its payment from `after`. No debts gives no steps but the before range.
- C3 [review] `load_dashboard` output is unchanged: the existing dashboard tests pass unedited, and `_fixed_sources` and `load_payoff` share `_debt_source`.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 payoff page and nav
Do: Add the `/payoff` page, server-rendering every step with no script yet, and the "Payoff" nav entry right after "Installments and loans".
Context: Router: `src/sonar/web/pages/payoff.py` with `build_router(db_path, today, templates)`, built like `pages/dashboard.py`. It calls `load_payoff(conn, today())` (N03) and renders `payoff.html` with the payoff and `charts.payoff_ticks([s.pay_now_cents for s in steps])` (N04). `app.py:119` includes the router after the debts router.
  D8: in `base.html:17`, add `("/payoff", "Payoff", "payoff")` after `/debts`, plus a `"payoff"` icon (a downward trend arrow, stroke path, 24×24). In `tests/web/test_shell.py:15`, add the entry to `NAV` after `/debts`.
  Template, extending `base.html` and built from `card`, `stat`, `amount`, `date`, `badge` and `empty`:
  - The page shows its estimate date in `#payoff-as-of` with the `date` macro. No steps renders `empty(..., id="payoff-empty")` linking to `/debts`, and nothing else.
  - D7: a page-local `range` macro renders "min – max", or one amount when min equals max, both with `amount(colored=false)`, inside a wrapper with `data-min-cents` and `data-max-cents`. `#payoff-fixed-now` is a stat with the before range.
  - D4/D6: `<div id="payoff-slider-block" hidden>` holds `<input type="range" id="payoff-slider" min="0" max="1000" step="1" value="0" aria-label="Debts to pay off now">` and the tick labels. One `<span data-tick="<n>" data-cents data-position>` per tick sits at `style="left: <percent>%"`, with row and translate classes copied from the runway scale (`components/charts.html:40-50`); a `row=None` tick shows a mark without text.
  - One `card` per step with attrs `data-step="<n>"` and `data-position="<pos>"`, never `hidden`. Inside it: `[data-part=pay-now]` (amount), `[data-part=freed]` (range), `[data-part=fixed-after]` (range), and a table with `id="payoff-step-<n>-debts"` whose rows carry `data-debt="<id>"` and `data-kind`. Its columns are kind badge, name, remaining (amount), rate (amount), every (`<n> month(s)` as at `debts.html:103`) and end/payoff date (`date` macro, or "–" when None).
  Classes for later JS: give the tick span `data-selected:font-semibold data-selected:text-ink` now. Rebuild `sonar.css` with the AGENTS.md Setup command.
Read: `src/sonar/web/pages/dashboard.py`, `src/sonar/web/app.py:100-125`, `src/sonar/web/templates/base.html:1-30`, `src/sonar/web/templates/debts.html:1-60`, `src/sonar/web/templates/components/charts.html:40-52`, `tests/html.py`, `tests/web/test_debts_page.py:1-90`, `tests/web/test_shell.py:1-60`
Write: `src/sonar/web/pages/payoff.py`, `src/sonar/web/templates/payoff.html`, `src/sonar/web/app.py`, `src/sonar/web/templates/base.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_payoff_page.py`, `tests/web/test_shell.py`
Test first: `tests/web/test_payoff_page.py` seeds three installments (anonymized names, through `add_debt`). `GET /payoff` renders three `[data-step]` cards whose pay-now `data-cents` equal `load_payoff` on the same DB, in ascending order. It fails with a 404.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_payoff_page.py tests/web/test_shell.py tests/web/test_templates_hygiene.py tests/test_architecture.py`
- C2 [review] Page tests cover several cases. Every step's pay-now, freed and fixed-after min/max cents match `load_payoff`. Each step's debts table lists its included debts in ladder order with `data-kind`. A min==max range shows one amount. The tick count and `data-cents` equal the steps.
- C3 [review] Page tests also cover these. `#payoff-slider-block` has `hidden` while no step card does. An empty DB shows `#payoff-empty` and no `#payoff-slider`. The nav lists Payoff right after Installments and loans, with `aria-current="page"` on `/payoff`.
- C4 [review] `app.py` only includes the router. There is no inline `<style>`; amounts use `amount`/`eur` and dates use `date`.
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/payoff-check.css" --minify && cmp -s "$TMPDIR/payoff-check.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 step slider script
Do: Add `src/sonar/web/static/payoff.js`, a small vanilla script that turns the hidden slider into the step picker of D5, and load it from `payoff.html`.
Context: D5: with `defer`, select `#payoff-slider`. Remove `hidden` from `#payoff-slider-block`, read each `[data-step]` card's `data-position`, and select step 1. Selecting step n works like this:
  - Set `hidden` on every other step card and remove it from card n.
  - Set `data-selected` on tick n only.
  - Set the slider's `value` to step n's position and its `aria-valuetext` to card n's `[data-part=pay-now]` text.
  - On `input`, select the step whose position is nearest to the value.
  - On `keydown`, ArrowLeft/ArrowDown/PageDown select n−1, ArrowRight/ArrowUp/PageUp select n+1, Home selects the first step and End the last, each with `preventDefault`.
  Touch only `hidden` and `data-*` attributes, never class names, because Tailwind does not scan `static/`. Make no network request.
  D9: the end of `payoff.html`'s content block holds `<script src="/static/payoff.js" defer></script>`, only when steps exist. The file starts with a comment on why it exists: the log-scale ticks need snapping that a native step range cannot do.
Read: `src/sonar/web/templates/payoff.html`, `tests/web/test_static.py`, `tests/web/test_payoff_page.py`
Write: `src/sonar/web/static/payoff.js`, `src/sonar/web/templates/payoff.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_static.py`, `tests/web/test_payoff_page.py`
Test first: in `tests/web/test_static.py`, `GET /static/payoff.js` answers 200 and mentions `payoff-slider`. In `tests/web/test_payoff_page.py`, a page with steps references `/static/payoff.js` and the empty page does not. Both fail before the file and tag exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_static.py tests/web/test_payoff_page.py`
- C2 [cmd] `! grep -nE 'fetch|XMLHttpRequest|htmx|classList|className' src/sonar/web/static/payoff.js`
- C3 [review] `payoff.js` implements every D5 behavior listed in Context, is plain ES with no dependency, and stays under about 60 lines.
- C4 [smoke] Start the app on a temp DB under `$TMPDIR` (never `data/sonar.db`). Add two installments with `POST /api/debts` (anonymized names). `curl -s http://127.0.0.1:8000/payoff | grep -c 'data-step='` prints 2, and `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/static/payoff.js` prints 200. Stop the app.
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/payoff-check.css" --minify && cmp -s "$TMPDIR/payoff-check.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 SPEC amendment
Do: Add one SPEC §13 bullet that records the Payoff page (D10).
Context: Append after the last line of `SPEC.md` (§13 starts at `SPEC.md:225`), in the style of the bullets above it. "Payoff ladder (§7, §9, §12):" says what the page covers in two or three sentences:
  - D1: open debts, ascending by remaining amount, as of the balance date.
  - D2: the cumulative pay-now total, and the before/after fixed payments per month as min and max over the dashboard's 12-month Fixed costs series, with freed = before − after for each.
  - D4: a log-scale step slider.
  - D5/D6/D9: a small `static/payoff.js` that switches steps with no request, overriding §12's inline-only scripts for this page; every step is readable without JS.
  - D7: the "min – max" display.
  It names no real debt, person or bank.
Read: `SPEC.md:225-254`
Write: `SPEC.md`
Test first: -
Done when:
- C1 [review] `git diff SPEC.md` adds exactly one bullet at the end of §13 and changes nothing else. The bullet covers D1, D2, D4, D5, D6, D7 and D9.
- C2 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 visual check of payoff
Do: Check `/payoff` in the browser pane at desktop and 375px, light and dark, following the config `visual_recipe` on a temp DB.
Context: After the recipe's import and settings, add four anonymized debts to the temp app through `POST /api/debts` (AGENTS.md table): small, mid and large monthly installments, and one installment with `interval_months: 3`, so that min and max differ. Use made-up names and match values; write none to a tracked file. Also open `/payoff` on a second fresh temp DB for the empty state. Defects go back to N05 or N06 as a replan.
Done when:
- C1 [visual] Desktop, light and dark: "Payoff" sits right after "Installments and loans" in the nav and is current. Above the slider are the pay-now total, freed min–max and fixed-after min–max; below it is the included debts table with kind, name, remaining, rate, every and end date.
- C2 [visual] The tick labels sit on a log scale, left to right ascending, and none overlap or leave the card. Dragging the slider snaps to a step and switches the shown figures and table with no network request (read_network_requests). The arrow keys move one step.
- C3 [visual] 375px, light and dark: no page-level horizontal scroll, the debts table fits or scrolls inside its card, and the slider and labels are readable and usable.
- C4 [visual] The empty DB shows the empty state with a link to `/debts` and no slider.

## N09 plan acceptance
Do: Check the whole plan against its Definition of done, SPEC §11 and §12, and the AGENTS.md rules.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [review] SPEC §11 still holds for the touched areas (the dashboard's Fixed costs output and the debts' remaining amounts are unchanged). SPEC §12 UI acceptance holds: `/payoff` extends `base.html`, uses the component macros, has no inline `<style>`, uses `eur`/`amount` for amounts and `date` for dates, and its tests use `tests/html.py` hooks.
- C4 [review] Per `git diff --stat` since N01: there is no new migration, no `/api` route and no change to AGENTS.md. `payoff_ladder` is pure and `today` stays a parameter. `tests/test_architecture.py` passes, and fixtures hold no real names, IBANs or ids.
- C5 [smoke] Start `uv run python -c` with `create_app` on a temp DB under `$TMPDIR`. `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/payoff` prints 200 and the body holds `payoff-empty`. Stop the app.

## Log

### N01 try 1 · 2026-10-06
check: FAIL C2
- C2 exit 1: +@layer properties{@supports (((-webkit-hyphens:none)) and (not (margin-trim:inline))) or ((-moz-orient:inline) and (not

### N01 replan 1 · 2026-10-06
plan: REPLANNED
- cause: Tailwind auto-detection scans untracked .plan/*.md, so building into tracked sonar.css adds classes (data-selected:*, table-row) and differs from HEAD
- C2 now resets the stray sonar.css to HEAD, builds into $TMPDIR, and asserts the tracked file is unchanged

### N01 try 1 · 2026-10-06
check: PASS 4/4

### N02 try 1 · 2026-10-06
exec: DONE · 1245 passed
- Added pure payoff.py (LadderDebt, PayoffStep, payoff_ladder) with tests
- ValueError message names the debt; min/max over months per D2
check: PASS 2/2
verify: PASS

### N04 try 1 · 2026-10-06
exec: DONE · 1250 passed
- payoff_ticks + PayoffTick in charts.py; greedy row pass extracted to _label_rows shared with runway_scale
- runway_scale passes max_rows=len(parts) so it never limits rows
check: PASS 2/2
verify: PASS

### N03 try 1 · 2026-10-06
exec: DONE · 1255 passed
- load_payoff + Payoff dataclass in cashflow/service.py; month_totals made public; _debt_source shared with _fixed_sources
- Payoff did not exist yet, so defined it in service.py
check: PASS 2/2
verify: PASS

### N05 try 1 · 2026-10-06
exec: DONE · 1266 passed
- Added /payoff router, payoff.html (all steps server-rendered, hidden slider block with ticks), Payoff nav entry and icon, rebuilt sonar.css
- Estimate date shows in the header on the empty state too; empty state hides the fixed-now stat
check: PASS 3/3
verify: PASS

### N06 try 1 · 2026-10-06
exec: DONE · 1269 passed
- Added static/payoff.js step picker (47 lines) and deferred script tag at the end of payoff.html's steps branch
- Tests: payoff.js served and mentions payoff-slider; page with steps loads it deferred, empty page does not; sonar.css unchanged
check: PASS 4/4
verify: PASS

### N07 try 1 · 2026-10-06
exec: DONE · 1269 tests passed
- Added Payoff ladder bullet to SPEC §13
- Covers D1 (debts by amount), D2 (cumulative total and freed), D4 (slider), D5/D6/D9 (payoff.js), D7 (display)
- No real names, all tests and lint pass
exec: DONE · 1269 passed
- Added the Payoff ladder bullet at the end of SPEC §13
- Bullet says ascending by remaining amount (D1)
check: PASS 1/1
verify: PASS
