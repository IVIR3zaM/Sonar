# Monthly income bar and group filters
status: DONE
created: 2026-11-06 · updated: 2026-11-06
goal: /monthly compares the month's income with each spending group's share and filters payments by group
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: On the Monthly page the owner sees at a glance how the month's income was used: what the Fixed, Keep the
lights on, Occasional and Uncategorized spending took of it and what was left (or how far spending ran past it),
and can jump from a group's stat to just that group's payments.

In scope: a pure income total and residual on `MonthlySpending`; a "Residual income" stat; pure segment geometry
and a macro drawing a two-zone bar (70% income zone, 30% overspend zone) under the group stats, with the income
labelled above the 70% mark, shaded spend segments, a residual segment and the total spent; the Fixed, Keep the
lights on, Occasional and transfers stats as links that filter the payment list to that group, kept across month
switches, with the active one marked and a reset; SPEC §13 bullets; tests; a rebuilt `sonar.css`.

Out of scope: the category and transfer tables, the existing category filter's behavior, the bar segments as
links, every other page, and the API.

Constraints: AGENTS.md rules: strict TDD, pure core with integer cents, components/ macros, no `<style>` element,
page tests on ids and `data-*` via `tests/html.py`, `sonar.css` rebuilt and committed; readable at 375px and in
dark mode; a visual gate at desktop and 375px, light and dark.

Definition of done: verify passes and, on the real sample, the bar and Residual income match the page's stats for
a normal month and for an overspend month when the sample has one, and each group link lists only that group.

## Decisions

- D1 Income = sum of credits (amount > 0) booked in the period in categories of type `income`; debits, transfers, other credits and uncategorized credits are not income. New field `MonthlySpending.income_cents`. | confirmed
- D2 Bar: track = 100% width; spend segments in order Fixed, Keep the lights on, Occasional, then Uncategorized only when non-zero; each width = |cents| / income × 70%; then a Residual segment only when residual > 0; cumulative width capped at 100%; no bar when income is 0. | confirmed
- D3 Spent for the bar and residual = sum of the four `GroupTotals` magnitudes, so the segments add up; residual = income − that spent, a `MonthlySpending.residual_cents` property, negative when overspent. | confirmed
- D4 Bar geometry as `income_bar(...)` in `src/sonar/web/charts.py` beside `need_bar` (charts.py:194-210), drawn by an `income_bar` macro in `components/charts.html`. | confirmed
- D5 Percent widths with one decimal via `Fraction` on cumulative ends, so widths sum to the rounded end (as `need_bar`). | confirmed
- D6 Bar drawn with HTML `div`s and `style="width: N%"` (precedent `debts.html:27`, `charts.html:53`), not SVG, so text never stretches. | confirmed
- D7 Inside label = short name (Fixed, Lights on, Occasional, Uncategorized, Left) over `charts.compact_eur` (charts.py:297); tier `always` at width ≥ 24%, `wide` (from `sm:`) at ≥ 12%, else none; every segment has `title` and `aria-label` with full name and `eur` amount; thresholds tunable at the gate. | confirmed
- D8 Colours from theme tokens so dark mode follows (`app.css:21-37`): income zone `bg-positive-soft`, overspend zone `bg-negative-soft`, spend segments `bg-accent/80`, `/60`, `/45`, `/30` in order, residual `bg-positive`. | confirmed
- D9 Under the bar one line "Spent X" (`data-part="spent"`), plus "Y over income" (`data-part="over"`) when spent exceeds income. | confirmed
- D10 Bar inside `#categories-card` after the stats grid (`monthly.html:71-81`), before `#category-totals`. | confirmed
- D11 Residual income stat right after Spent, signed `amount` with `colored=true` (negative shows as negative), id `residual-income`, shown only when income > 0 like the bar. | confirmed
- D12 Group filter: query `group` = `fixed`, `lights_on`, `occasional` or `transfer` (the groups.py:18-22 values); pure `only_group(payments, category_types, group)` in monthly.py; any other value answers 404 like a bad month (pages/monthly.py:27-30). | confirmed
- D13 Group and category filters exclude each other: a group link drops `category`, a category link drops `group`; a URL with both applies the category only. Month links and the picker keep whichever is set. | confirmed
- D14 Stat links: `stat` (components/stat.html:7) gains optional `href` and `current`; the whole stat is the link, `data-group` on it, `aria-current="true"` when active; clicking the active one clears it; a `#group-filter` banner like `#category-filter` (monthly.html:150-158) with count, sum and a `#reset-group` "Show all". | confirmed
- D15 `/api/monthly` stays unchanged as requested, although §13 API parity (`SPEC.md:253`) asks for page reads in the API; the SPEC bullets say so. | confirmed
- D16 The gate is pre-authorized: start the app on a temp DB, import `data/categories.toml` and the newest sample (config `visual_recipe`, `preauthorized`). | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | income bar and residual stat | exec | - | gpt-6.1-sol@high/sonnet | 1 | 1 | DONE | |
| N02 | group filter links | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N03 | visual check | gate | N02 | -/sonnet | 0 | 0 | DONE | |

## N01 income bar and residual stat
Do: In `src/sonar/cashflow/monthly.py:66-103` add `MonthlySpending.income_cents` = sum of credits (amount > 0) in the
  period whose category type is `groups.INCOME` (groups.py:18); uncategorized and other credits are not income. Add
  property `residual_cents` = income − spent, spent = sum of the four `GroupTotals` magnitudes (group cents are
  negative, groups.py:50-55). Add pure `income_bar(groups, income_cents)` to `src/sonar/web/charts.py` by `need_bar`
  (charts.py:201): `None` when income is 0, else a frozen dataclass of `segments`, `spent_cents`, `over_cents`
  (spent − income if positive, else 0). Add an `income_bar` macro to `components/charts.html`; call it in
  `monthly.html` inside `#categories-card` after the stats grid (monthly.html:70-81), before `#category-totals`, and
  add a "Residual income" stat right after Spent. Append a §13 bullet "Monthly income bar (§9, §12)" to `SPEC.md`
  after line 274 with the rules below, saying `/api/monthly` stays unchanged although §13 API parity (`SPEC.md:253`)
  asks for page reads in the API. Rebuild `sonar.css`.
Context: Segments in order `fixed`, `lights_on`, `occasional`, `uncategorized` (only when non-zero), `residual` (only
  when residual > 0); each has `part`, positive `cents`, width, label tier. Geometry in integer tenths of a percent:
  end = round(Fraction(cumulative_cents * 700, income)) capped at 1000; width = end − previous end (a segment past the
  cap gets 0); render one decimal ("23.3"). Example: income 600000, fixed 200000, lights on 100000, occasional 50000
  → 23.3, 11.7, 5.8, residual 250000 at 29.2, end 70.0. Tier `always` at width ≥ 24.0, `wide` (shown from `sm:`) at
  ≥ 12.0, else no label. Label = short name (Fixed, Lights on, Occasional, Uncategorized, Left) over
  `charts.compact_eur` (charts.py:297), `truncate`. Each segment's `title` and `aria-label` = full name (Fixed
  payments, Keep the lights on, Occasional payments, Uncategorized, Residual income) and `eur` amount.
  Markup: `div`s with `style="width: N%"` (as `charts.html:53`), no SVG, no `<style>`. Root `id="income-bar"` with
  `data-income-cents`, `data-spent-cents`. Behind the segments a 70% zone `data-zone="income"` `bg-positive-soft` and
  a 30% zone `data-zone="overspend"` `bg-negative-soft`. Segments `bg-accent/80`, `/60`, `/45`, `/30` in order,
  residual `bg-positive`; hooks `data-segment`, `data-cents`, `data-width`. Income label above the bar centred on the
  70% mark, never inside: `data-part="income"`, `data-cents`, `eur`. Below, one line "Spent X" (`data-part="spent"`,
  `data-cents`) plus "Y over income" (`data-part="over"`, `data-cents`) when over > 0. Residual stat:
  `amount(spending.residual_cents, id="residual-income", colored=true)`, only when income > 0.
Read: `src/sonar/cashflow/monthly.py:40-105`, `src/sonar/categorization/groups.py:14-95`, `src/sonar/web/charts.py:195-212,297-310`, `src/sonar/web/templates/components/charts.html:40-58,300-320`,
  `components/amount.html:10`, `components/stat.html:7`, `monthly.html:66-84`, `tests/web/test_monthly_page.py:1-64`, `tests/html.py`, `tests/web/test_charts_bare_minimum.py:1-40`, `src/sonar/web/static/src/app.css:21-37`, `SPEC.md:253,268-274`
Write: `src/sonar/cashflow/monthly.py`, `src/sonar/web/charts.py`, `src/sonar/web/templates/monthly.html`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/static/sonar.css`, `SPEC.md`, `tests/cashflow/test_monthly.py`, `tests/web/test_charts_income_bar.py`, `tests/web/test_monthly_income_bar.py`
Test first: `monthly_spending` sums only income-type credits; `residual_cents` < 0 when overspent; `income_bar` gives the
  example's widths and tiers, omits a zero Uncategorized, drops the residual and sets `over_cents` when spent > income,
  caps the end at 100.0, is `None` for income 0; the page shows `#income-bar` with segment cents equal to the group
  stats and `#residual-income`, and neither in a month without income.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_monthly.py tests/web/test_charts_income_bar.py tests/web/test_monthly_income_bar.py tests/web/test_monthly_page.py tests/web/test_templates_hygiene.py`
- C2 [review] income, residual, geometry pure integer-cent code; tests cover example, overspend, cap, zero Uncategorized, income 0; page tests use only ids and `data-*` via `tests/html.py`
- C3 [review] macro in `components/charts.html`, no `<style>`, income labelled above the 70% mark, the zone and segment classes above, `title` and `aria-label` on every segment; other stats, tables and API unchanged
- C4 [review] the new SPEC §13 bullet matches the code for income, spent, residual, segments, labels, Spent line and API
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-check.css" --minify && cmp "$TMPDIR/plz-check.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 group filter links
Do: Add pure `only_group(payments, category_types, group)` to `src/sonar/cashflow/monthly.py` (D12). Read a `group`
  query in `src/sonar/web/pages/monthly.py` (404 on an unknown value, D12; category wins over group, D13) and pass
  the filtered payments and active group to the template. Give `stat` optional `href` and `current` (D14) and make
  the Fixed payments, Keep the lights on, Occasional payments and transfers stats in `monthly.html:71-80` links to
  the same month with `group`; add the `#group-filter` banner. Extend `month_url`/`month_link` and the picker's
  hidden input (`monthly.html:21-27,44-49`) to keep the group (D13). Append a §13 bullet "Monthly group filter
  (§9, §12)" to `SPEC.md` (D12-D15). Rebuild `sonar.css`.
Context: Links use the page's `boost` attrs (monthly.html:20). A group link drops `category`; a category row link
  drops `group`. Clicking the active stat links back to the unfiltered month. Banner text "Only <group label>"
  (`groups.LABELS`, groups.py:26-32) with count and sum of the listed payments. Transfer = debits in `transfer`
  categories (payments are debits only, monthly.py:79-83).
Read: `src/sonar/cashflow/monthly.py:100-110`, `src/sonar/categorization/groups.py:18-38`, `src/sonar/web/pages/monthly.py`,
  `src/sonar/web/templates/monthly.html:18-82,148-160`, `src/sonar/web/templates/components/stat.html`,
  `tests/web/test_monthly_page.py:1-64,160-200`, `tests/web/test_components.py`, `tests/html.py`
Write: `src/sonar/cashflow/monthly.py`, `src/sonar/web/pages/monthly.py`, `src/sonar/web/templates/monthly.html`, `src/sonar/web/templates/components/stat.html`, `src/sonar/web/static/sonar.css`, `SPEC.md`, `tests/cashflow/test_monthly.py`, `tests/web/test_components.py`, `tests/web/test_monthly_group_filter.py`
Test first: `only_group` keeps only that group's payments in order; each of the four stats links to
  `?month=…&group=…`; `group=fixed` lists only fixed payments, marks that stat `aria-current="true"` and shows
  `#group-filter` with `#reset-group`; older/newer and the picker keep `group`; `group=bogus` is 404; a URL with
  both `category` and `group` filters by category only; `stat` without `href` renders as before.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_monthly.py tests/web/test_monthly_group_filter.py tests/web/test_monthly_page.py tests/web/test_components.py tests/web/test_templates_hygiene.py`
- C2 [review] tests cover all four groups, the active mark, reset, month switches, 404, the category/group rule and
  the unlinked `stat`; they use only ids, `href`, `aria-current` and `data-*` via `tests/html.py`
- C3 [review] the bar segments are not links; the category filter, tables and API behave as before
- C4 [review] the new SPEC §13 bullet matches the code for D12-D15
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-check.css" --minify && cmp "$TMPDIR/plz-check.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N03 visual check
Do: gate, pre-authorized (D16). Run `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`,
  then start the app per config `visual_recipe` on `$TMPDIR/sonar-visual.db`. Import the newest file in `samples/`
  on /import; on /settings set salary day 26 and a balance as of the sample's last booking date. Using
  `GET /api/monthly?month=YYYY-MM` group totals, pick a month with residual and, if any, one where spent exceeds
  income; check /monthly for both at desktop and 375px, light and dark (read_page first, scaled screenshots only
  where layout matters); click each group stat and switch month once with a group set. Stop the app.
Done when:
- C1 [visual] `#income-bar` sits under the stats; segment amounts equal the group stats; the income label sits above
  the bar at the 70% mark; Residual income equals income − spent, negative in an overspend month
- C2 [visual] the two zones have distinct colours that show through the spend segments; the residual stands out in
  another colour; the Spent line shows, with "over income" in an overspend month
- C3 [visual] each group stat lists only that group's payments, is marked active, and Show all clears it; the group
  stays set across a month switch
- C4 [visual] at 375px no label overflows its segment or the card, no horizontal page scroll; light and dark readable

## Log

### N01 try 1 · 2026-11-06
exec: BLOCKED · Brief references missing decisions D5, D7 and D8: label-tier thresholds/content and required zone classes are unspecified.

### N01 replan 1 · 2026-11-06
plan: REPLANNED
- cause: brief cited D5, D7, D8 by number without restating label tiers, label content or zone/segment classes
- new brief restates every needed decision inline: tenths-of-percent geometry with cap, tier thresholds 24/12, short and full labels, zone and segment classes, hooks, Spent/over line, residual stat
- pins income_bar return shape (None at income 0; segments, spent_cents, over_cents) and SPEC bullet content; criteria no longer cite decision ids

### N01 try 1 · 2026-11-06
exec: DONE · 2231 passed; ruff check and format clean; CSS rebuild matches
- Added income credits, residual stat, integer geometry, accessible income bar and SPEC §13 amendment with tests.
- Income uses categorized positive credits; residual uses four spending groups; API remains unchanged.
check: PASS 3/3
verify: PASS

### N02 try 1 · 2026-11-06
exec: DONE · 2240 tests passed; ruff check and format clean; CSS rebuild matches
- Added pure group filtering, linked stats, active/reset banner and month filter persistence with regression tests.
- Documented D12-D15 in SPEC §13; category takes precedence and transfer list remains debit-only.
check: PASS 3/3
verify: PASS
