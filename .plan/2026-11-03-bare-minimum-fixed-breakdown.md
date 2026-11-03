# Bare minimum fixed-cost breakdown
status: RUNNING
created: 2026-11-03 · updated: 2026-11-03
goal: the Bare minimum card and /api/dashboard show what the fixed-cost monthly equivalent is made of, by category
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The owner opens the dashboard and, inside the Bare minimum card, sees which categories and payments make up
the fixed-cost monthly equivalent, so the biggest insurance or the forgotten subscription stands out at a glance.

In scope: A pure breakdown of the current fixed payments (recurring rows plus debt schedules standing in for their
linked payments) at their monthly equivalent, grouped by category with debt-kind and "Other" fallbacks; its wiring
into the dashboard model and `/api/dashboard`; a "What fixed costs are made of" subsection in the Bare minimum card;
a SPEC §13 amendment describing it.

Out of scope: Hand-picked areas merging several categories, forecast or per-cycle amounts, any change to the bare
minimum figures, the Fixed costs card or other cards.

Constraints: AGENTS.md rules: strict TDD, pure functions with `today` a parameter, integer cents, DB access only via
stores, `components/` macros, `amount` macro (eur filter), no inline style, page tests on ids and `data-*` through
`tests/html.py`, `sonar.css` rebuilt and committed. Readable at 375px. Confirmed Decisions D1-D9.

Definition of done: The subsection renders in the Bare minimum card with groups largest first and their payments,
`/api/dashboard` carries the same data, the groups sum exactly to the Fixed costs monthly equivalent, the full
verify passes, the visual gate passes at desktop and 375px in light and dark, and the final check confirms SPEC §11
and §12.

## Decisions

- D1 A payment's monthly amount uses the Monthly equivalent's own rule (`forecast.py:216` `_year_total`): its planned occurrences in the 12 calendar months from the estimate date's month, divided by 12, so a steady payment is amount × 12 / interval and a debt ending or a payment paused inside the year counts only its planned months; a source with a zero 12-month total is left out | confirmed
- D2 Rounding: monthly cents are apportioned by largest remainder (floor each payment's year total / 12, hand the leftover cents to the largest remainders, ties by name), so payments sum to their group and groups sum to the Monthly equivalent exactly | confirmed
- D3 Group label: a recurring payment's category name (whatever its group); a debt schedule takes the category of its first linked payment that has one, else "Loans" (loan) or "Installments" (installment); any other uncategorized payment goes under "Other" | confirmed
- D4 Share is group total × 100 / breakdown total as an integer percent rounded half up, 0 when the total is 0; shares are not forced to add up to 100 | confirmed
- D5 Placement and API: the subsection closes the Bare minimum card in both its hint and numbers states and is absent when no payment is listed; `/api/dashboard` gets a top-level `fixed_breakdown` (`total_cents`, `count`, `groups`: [`name`, `total_cents`, `share_percent`, `payments`: [`name`, `monthly_cents`]]), always an object, because `bare_minimum` is null on a hint | confirmed
- D6 Layout: each group is a collapsed `<details>` whose summary shows name, share and total; its payments are a compact name-and-amount list inside; the header line states the total a month and the payment count | confirmed
- D7 Sorting: groups by total descending then name; payments by monthly amount descending then name | confirmed
- D8 The visual gate is pre-authorized: config `visual_recipe` on `$TMPDIR/sonar-visual.db`, after `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"` | confirmed
- D9 The behavior is written as one new SPEC §13 bullet "Fixed costs breakdown (§9, §12, API)" | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | breakdown math and SPEC | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 1 | DONE | |
| N03 | dashboard and API wiring | exec | N02 | gpt-6.1-sol@medium/sonnet | 1 | 1 | DONE | |
| N04 | breakdown subsection | exec | N03 | gpt-6.1-sol@medium/sonnet | 0 | 0 | TODO | |
| N05 | visual check | gate | N04 | -/sonnet | 0 | 0 | TODO | |
| N06 | plan acceptance | check | N05 | -/sonnet | 0 | 0 | TODO | |

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

## N02 breakdown math and SPEC
Do: Add a pure `fixed_breakdown(labelled, today)` to `src/sonar/cashflow/forecast.py` beside `fixed_costs`
  (`forecast.py:182`), taking `(label, FixedSource)` pairs and returning frozen dataclasses `FixedBreakdown`
  (`total_cents`, `count`, `groups`), `BreakdownGroup` (`name`, `total_cents`, `share_percent`, `payments`) and
  `BreakdownPayment` (`name`, `monthly_cents`). Split `_year_total` (`forecast.py:216`) so one per-source helper
  gives each source's 12-month planned cents and both functions use it. Append the SPEC §13 bullet.
Context: Code uses D1, D2, D4, D7; labels arrive from the caller (D3 is coded in N03). The SPEC bullet states all of
  D1-D7 below, in plain words.
  D1 a payment's monthly amount = its planned occurrences in the 12 calendar months from the estimate date's month
  (the Monthly equivalent's rule), / 12; a debt ending or a payment paused inside the year counts only its planned
  months; a source with a 0 12-month total is left out.
  D2 largest remainder: floor each source's year cents / 12; the leftover (round-half-up of the summed year cents
  / 12, as `forecast.py:189`, minus the floors) goes one cent each to the largest remainders, ties by name; a group
  total = sum of its payments, so groups sum exactly to the Monthly equivalent.
  D3 group label: a recurring payment's category name (whatever its group); a debt schedule takes the category of
  its first linked payment that has one, else "Loans" (loan) or "Installments" (installment); any other
  uncategorized payment goes under "Other".
  D4 share = group total × 100 / breakdown total, integer percent rounded half up, 0 when the total is 0; shares
  are not forced to add to 100.
  D5 the subsection closes the Bare minimum card in both its hint and numbers states and is absent when no payment
  is listed; `/api/dashboard` has a top-level `fixed_breakdown` {`total_cents`, `count`, `groups`: [{`name`,
  `total_cents`, `share_percent`, `payments`: [{`name`, `monthly_cents`}]}]}, always an object.
  D6 each group is a collapsed `<details>` whose summary shows name, share and total, with a compact name-and-amount
  list of its payments inside; a header line states the total a month and the payment count.
  D7 groups by total desc then name; payments by monthly desc then name.
  D9 one bullet "Fixed costs breakdown (§9, §12, API)" appended after `SPEC.md:266`. `today` stays a parameter;
  integer cents only.
Read: `src/sonar/cashflow/forecast.py`, `tests/cashflow/test_forecast.py`, `SPEC.md:225-266`
Write: `src/sonar/cashflow/forecast.py`, `tests/cashflow/test_fixed_breakdown.py`, `SPEC.md`
Test first: with a monthly, a 2-monthly, a yearly, an odd-cent quarterly, a debt-like source ending inside the
  year and a source paused all year, `fixed_breakdown(...).total_cents == fixed_costs(...).monthly_equivalent_cents`,
  each group's total equals the sum of its payments, the paused source is absent, and order follows D7.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_fixed_breakdown.py tests/cashflow/test_forecast.py`
- C2 [review] `tests/cashflow/test_fixed_breakdown.py` covers the sum-to-Monthly-equivalent rule with remainders
  that need apportioning, group sums, the zero-total exclusion, share rounding and the 0-total share, and D7 order
- C3 [review] `fixed_costs` and `fixed_breakdown` share one per-source year-total helper; no date.today(), no float
- C4 [review] SPEC.md has one new §13 bullet stating D1-D7 as given in Context, including the D5 API shape
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 dashboard and API wiring
Do: Add `fixed_breakdown: forecast.FixedBreakdown` to `Dashboard` (`src/sonar/cashflow/service.py:54`) and set it in
  `load_dashboard` (`service.py:139`) to `forecast.fixed_breakdown(labelled, estimate_date)` before the early return
  (`service.py:189`), so both paths carry it. Replace `_fixed_sources` (`service.py:489`) with one
  `_labelled_fixed_sources(payments, views, txs, links) -> tuple[tuple[str, FixedSource], ...]` that keeps the
  linked-payment exclusion and attaches each source's D3 label; `load_dashboard:155` and `load_payoff:114` take the
  plain sources from it (`tuple(source for _, source in labelled)`), so the exclusion stays in one place.
  `/api/dashboard` serializes the new field through `_jsonable` (`src/sonar/web/api/cashflow.py:57`) unchanged.
Context: Domain API, done and tested (`src/sonar/cashflow/forecast.py:91-109,219-256`):
  `fixed_breakdown(labelled: Sequence[tuple[str, FixedSource]], today: date) -> FixedBreakdown`;
  `FixedBreakdown(total_cents, count, groups)`, `BreakdownGroup(name, total_cents, share_percent, payments)`,
  `BreakdownPayment(name, monthly_cents)`; its total equals `fixed_costs(...).monthly_equivalent_cents` for the same
  sources and date; zero-year sources are dropped. `FixedSource` is at `forecast.py:38`.
  D3 labels: recurring payment -> `RecurringPayment.category` (`src/sonar/recurring/store.py:38`), else "Other";
  debt schedule -> `category` of the first `view.linked_payments` entry that has one (`src/sonar/debts/store.py:50-54`),
  else "Loans" for a `Loan` and "Installments" for an `Installment` (`src/sonar/debts/model.py:49,72`).
  D5 `/api/dashboard` has a top-level `fixed_breakdown` object, filled with or without salary day or balance.
  Helpers: `add_manual(conn, name, category, period)` (`src/sonar/recurring/store.py:69`), `_monthly`,
  `_insert_detected`, `_insert_tx`, `_installment` in `tests/cashflow/test_service.py:44-128`; loan fixture
  `tests/cashflow/test_service.py:298-308`; linking via mandate as `tests/cashflow/test_service_bare_minimum.py:44-47`.
Read: `src/sonar/cashflow/service.py:54-200,476-530`, `src/sonar/cashflow/forecast.py:38-44,91-109,219-256`,
  `tests/cashflow/test_service_bare_minimum.py:1-60`, `tests/cashflow/test_service.py:38-130,295-330`,
  `tests/web/test_api_dashboard.py:1-75`
Write: `src/sonar/cashflow/service.py`, `tests/cashflow/test_service_fixed_breakdown.py`, `tests/web/test_api_dashboard.py`
Test first: without a salary day, a DB with a categorized manual payment, an uncategorized one, a loan linked to an
  uncategorized detected payment, an installment linked to a categorized one and an installment with no link yields
  groups named by category, "Other", "Loans" and "Installments"; group totals sum to
  `board.fixed_costs.monthly_equivalent_cents`; each linked payment appears only under its debt's name.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_service_fixed_breakdown.py tests/web/test_api_dashboard.py`
- C2 [review] the service test covers each D3 label (category, "Other", "Loans", "Installments", a debt taking its
  linked payment's category), each linked payment counted once, the sum rule, and the breakdown filled without a
  salary day
- C3 [review] an API test asserts `body["fixed_breakdown"] == _jsonable(board.fixed_breakdown)` and that it is a
  dict without a salary day
- C4 [review] the linked-payment exclusion exists once in `service.py`; `load_payoff` uses the same helper; no SQL
  outside stores
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 breakdown subsection
Do: In `src/sonar/web/templates/index.html`, close the Bare minimum card (`index.html:219-297`, after the
  hint/numbers `{% endif %}`) with a subsection `id="fixed-breakdown"` (`data-total`, `data-count`): an h3 "What
  fixed costs are made of", a header line with the total a month and the payment count, and one collapsed
  `<details data-group>` per group whose summary has `data-field` name, share (`data-percent`) and total, holding
  a list of `data-payment` items with `data-field` name and amount. Rebuild and commit `sonar.css`.
Context: D5 shown in hint and numbers states, absent when `count` is 0. D6 collapsed groups, compact list, readable
  at 375px with no horizontal page scroll. D7 order as given by the model. Amounts via the `amount` macro
  (`components/amount.html`), `colored=false`; reuse `details_summary` (`index.html:17`); no inline `<style>`.
  Page-test helpers `tests/html.py:19-44`; seed helpers `tests/web/test_dashboard_bare_minimum.py:1-40`.
Read: `src/sonar/web/templates/index.html:1-20,219-297`, `tests/web/test_dashboard_bare_minimum.py`, `tests/html.py`
Write: `src/sonar/web/templates/index.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_dashboard_fixed_breakdown.py`
Test first: the dashboard page with fixed payments has `#fixed-breakdown` inside `#bare-minimum-card` whose groups,
  shares, totals and payments equal `load_dashboard(...).fixed_breakdown`, also in the hint state; with no fixed
  payment there is no `#fixed-breakdown`.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_dashboard_fixed_breakdown.py tests/web/test_templates_hygiene.py`
- C2 [review] the tests assert only ids and `data-*` through `tests/html.py`, cover hint and numbers states,
  group order, payment order, the header total and count, and the absent case
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-check.css" --minify && cmp "$TMPDIR/plz-check.css" src/sonar/web/static/sonar.css`
  shows `sonar.css` is rebuilt from the current templates
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 visual check
Do: gate, pre-authorized (D8). Run `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`,
  then start the app per config `visual_recipe` on `$TMPDIR/sonar-visual.db`. Import the newest file in `samples/`
  on /import, then on /settings set salary day 26 and a balance as of the sample's last booking date. Check / at
  desktop and 375px, light and dark (read_page first, scaled screenshots only where layout matters), comparing the
  subsection with `GET /api/dashboard` `fixed_breakdown` and `fixed_costs.monthly_equivalent_cents`. Open the
  largest group. Then clear the salary day, check the hint state still shows the subsection, and stop the app.
Done when:
- C1 [visual] the "What fixed costs are made of" subsection closes the Bare minimum card; its header total equals
  the Fixed costs Monthly equivalent and its count and group totals equal `/api/dashboard` `fixed_breakdown`
- C2 [visual] groups run largest first; an opened group lists its payments largest first with name and amount
- C3 [visual] at 375px nothing is cut off or overflows the card; light and dark are both readable
- C4 [visual] without a salary day the card shows the hint and the subsection still shows

## N06 plan acceptance
Do: Whole-plan check: run the full verify, then confirm SPEC §11 (acceptance checklist) and §12 (UI) still hold for
  the dashboard and that the new §13 bullet matches the code.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [review] SPEC §11 items touching the dashboard and Fixed costs (`SPEC.md:162-177`) still hold; the Bare
  minimum figures and the Fixed costs card are unchanged in behavior
- C3 [review] SPEC §12 UI rules hold for the subsection: `base.html` page, `components/` macros, `amount` for money,
  no inline `<style>`, page tests on ids and `data-*`, `sonar.css` rebuilt and committed
- C4 [review] the SPEC §13 "Fixed costs breakdown" bullet matches `forecast.py`, `service.py`, the API key and the
  template, including D1-D7

## Log

### N01 try 1 · 2026-11-03
check: PASS 5/5

### N02 try 1 · 2026-11-03
exec: BLOCKED · C4 requires a SPEC bullet stating D1-D7, but the brief omits D3 label rules and D6 behavior; provide those decisions to document them without guessing.

### N02 replan 1 · 2026-11-03
plan: REPLANNED
- cause: C4 asked the SPEC bullet to state D1-D7 but the brief restated only D1, D2, D4, D7
- brief now restates D3, D5, D6 in full for the SPEC text; code scope unchanged (labels still from caller, D3 coded in N03)

### N02 try 1 · 2026-11-03
exec: DONE · 2112 passed; ruff check and format clean
- Added frozen breakdown models, largest-remainder monthly allocation, grouped shares and ordering, and shared per-source yearly totals.
- Added seven domain tests and the SPEC §13 Fixed costs breakdown bullet; retained payments with positive yearly totals even when their monthly amount rounds to zero.
check: PASS 2/2
verify: PASS

### N03 try 1 · 2026-11-03
exec: BLOCKED · Brief omits the fixed-breakdown domain API and its source from Read; need its type and callable signature to wire Dashboard without guessing.

### N03 replan 1 · 2026-11-03
plan: REPLANNED
- cause: brief did not name the N02 domain API (fixed_breakdown signature, dataclasses) nor put forecast.py in Read
- brief now cites forecast.py:91-109,219-256 with the exact signature and fields, names the single _labelled_fixed_sources helper shared by load_dashboard and load_payoff, and adds the linked-category debt case to the test

### N03 try 1 · 2026-11-03
exec: DONE · 2117 passed; ruff check and format clean
- Added labelled fixed sources shared by dashboard and payoff; populated fixed_breakdown before setup returns.
- Covered all D3 labels, debt deduplication, total equality across salary and balance states, and API serialization; observed five failures before implementation.
check: PASS 2/2
verify: PASS
