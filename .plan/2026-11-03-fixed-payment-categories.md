# Fixed payment categories
status: RUNNING
created: 2026-11-03 · updated: 2026-11-03
goal: every fixed payment in the dashboard breakdown sits under a real category, for hand-entered payments and unlinked debts alike
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The dashboard's fixed costs breakdown groups each payment under the category the owner thinks of it as. Today a
hand-entered payment always falls into "Other" because it can never carry a category, and a debt without a linked
recurring payment falls into "Installments" or "Loans" even when its bank debits are already categorized.

In scope: an optional category on hand-entered (manual) recurring payments, limited to `fixed` categories, settable
in the add and edit forms of the Fixed payments page and as `category` in POST and PUT /api/recurring; detected
payments keep their bookings' category and stay uneditable. A debt with no linked recurring payment takes its label
from its latest categorized matched debit before the by-kind fallback. SPEC §13 bullet and the AGENTS.md endpoint
table follow.

Out of scope: categorization rules, recategorizing transactions, labels of debts that have linked payments, and any
other card's grouping beyond what follows from the new category.

Constraints: AGENTS.md rules: strict TDD, pure domain functions, store-only DB access, no migration unless the
schema needs one, components macros, no inline style, page tests on ids and `data-*` through `tests/html.py`,
`sonar.css` rebuilt and committed. Decisions D1-D7.

Definition of done: a manual payment in Subscriptions shows in the Subscriptions group of `fixed_breakdown`; an
unlinked debt whose matched debits are in Loans & Installments shows in that group; the API and both forms
round-trip the category; full verify passes; the visual gate passes on Fixed payments (add and edit forms) and the
dashboard breakdown; the final check confirms SPEC §11 and §12.

## Decisions

- D1 No migration: manual categories reuse `recurring_payments.category` (`src/sonar/migrations/0003_recurring.sql:12`); category rename and delete already rewrite or clear it (`src/sonar/categorization/store.py:166-185`), so hand-entered data survives | confirmed · no migration
- D2 Validation sits in the web layer through one new `fixed_category_names(conn)` in `categorization/store.py`, sorted by name, which also feeds the form options; `add_manual` stays unvalidated so existing callers and tests keep working | confirmed · web layer plus helper
- D3 API: POST `category` optional (omitted or null = none); PUT `category` omitted keeps, null or blank clears, otherwise the exact, case-sensitive name of a `fixed` category; unknown or non-fixed name is a 400 with `field: category`; any `category` key in PUT on a detected payment is a 400 with `field: category` | confirmed · as stated
- D4 Page: the add form and the edit form of manual payments get a "Category" select of "None" plus the fixed categories; detected rows get no select (their badge stays). A manual payment whose category later stops being `fixed` keeps it until edited; its edit select then preselects None and saving clears it | confirmed · accept
- D5 Debt label: a debt with no linked recurring payment uses the category of its latest matched debit that has a category (latest booking date; ties go to the later row in `transactions_with_category` order), else Loans or Installments by kind; a debt with linked payments keeps today's rule (first linked payment's category, else by kind) | confirmed · skip uncategorized debits, linked debts unchanged
- D6 Docs: one new SPEC §13 bullet "Manual payment categories" that extends the Recurring descriptions PUT (`SPEC.md:251`) and overrides the debt-label clause of "Fixed costs breakdown" (`SPEC.md:267`); AGENTS.md endpoint table adds `category` to POST and PUT `/recurring` (`AGENTS.md:101-102`) | confirmed · new overriding bullet
- D7 The visual gate is pre-authorized: run `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"` first, then config `visual_recipe` on that temp DB | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | manual category API and docs | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N03 | breakdown labels from categories | exec | N02 | gpt-6.1-sol@medium/sonnet | 0 | 1 | TODO | |
| N04 | category in Fixed payments forms | exec | N02,N03 | gpt-6.1-sol@medium/sonnet | 0 | 0 | TODO | |
| N05 | visual check | gate | N03,N04 | -/sonnet | 0 | 0 | TODO | |
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

## N02 manual category API and docs
Do: Let hand-entered payments carry a fixed category through the JSON API, and document it. Add
  `fixed_category_names(conn)` to `categorization/store.py` (names of `fixed` categories, sorted by name), and
  `set_category(conn, id, category)` to `recurring/store.py` (raises `PaymentNotFound`; refuses a detected payment
  with a new `NotManual` error). Wire `category` into POST and PUT /api/recurring, then add the SPEC §13 bullet and
  the AGENTS.md table fields.
Context: D2 web-layer validation via `fixed_category_names`; `add_manual` (`src/sonar/recurring/store.py:69`) stays
  unvalidated. D3 POST optional, PUT omitted keeps / null or blank clears / else exact fixed name; unknown or
  non-fixed name and any PUT `category` on a detected payment are 400 `field: category`; validate before any write.
  POST today passes None (`src/sonar/web/api/recurring.py:213`); models at `:44-58`, PUT at `:224-260`. D1 no
  migration. D6 new §13 bullet "Manual payment categories": manual-only fixed category, the API rules above, and the
  breakdown debt label of D5 (unlinked debt: latest categorized matched debit, else by kind; linked: unchanged),
  stating it overrides the debt-label clause at `SPEC.md:267`; add `category` to `AGENTS.md:101-102`.
Read: `src/sonar/web/api/recurring.py`, `src/sonar/recurring/store.py`, `src/sonar/categorization/store.py:130-185`,
  `tests/web/test_api_recurring.py`, `tests/recurring/test_store_description.py`, `SPEC.md:251`, `SPEC.md:267`
Write: `src/sonar/categorization/store.py`, `src/sonar/recurring/store.py`, `src/sonar/web/api/recurring.py`,
  `tests/categorization/test_store_fixed_names.py`, `tests/recurring/test_store_category.py`,
  `tests/web/test_api_recurring_category.py`, `SPEC.md`, `AGENTS.md`
Test first: POST /api/recurring with `category: "Subscriptions"` returns 201 and GET lists that category; PUT on a
  detected payment with `category` is a 400 `field: category`.
Done when:
- C1 [cmd] `uv run pytest -q tests/categorization/test_store_fixed_names.py tests/recurring/test_store_category.py tests/web/test_api_recurring_category.py`
- C2 [review] tests cover: POST with a fixed category, without one, with an unknown and a `lights_on` name (400,
  `field: category`, nothing stored); PUT set, keep on omit, clear on null and on blank, unknown id 404, detected
  payment 400 with its category unchanged; `fixed_category_names` lists only `fixed` names, sorted
- C3 [review] `set_category` is the only new DB write; validation runs before any write; no new migration file
- C4 [review] the SPEC §13 bullet states D3 and D5 and the override of `SPEC.md:267`; `AGENTS.md` rows for POST and
  PUT `/recurring` list `category`
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 breakdown labels from categories
Do: Label an unlinked debt in the fixed breakdown by its latest categorized matched debit, and prove manual payment
  categories already flow through. Add a pure `latest_category(debt, rows)` to `debts/model.py` next to
  `last_payment_date` (`src/sonar/debts/model.py:237-244`), reusing `matches`. Pass the categorized rows into
  `_labelled_fixed_sources` (`src/sonar/cashflow/service.py:494-523`; callers `:115` and `:158`) and use it between
  the linked-payment category and the by-kind fallback, only for debts with no linked payment.
Context: D5 latest matched debit that has a category (latest booking date, ties to the later row), else Loans or
  Installments; debts with linked payments keep today's rule. `add_manual` already stores a category
  (`src/sonar/recurring/store.py:69`); no validation here. The existing service test
  (`tests/cashflow/test_service_fixed_breakdown.py:20-70`) must keep passing unchanged. `today` stays a parameter.
  Runs after N02 is committed, so the full verify sees N02's API and tests; changes in the tree under this Write
  set are this node's to keep, fix or finish.
Read: `src/sonar/debts/model.py`, `src/sonar/cashflow/service.py:100-190`, `src/sonar/cashflow/service.py:494-540`,
  `tests/cashflow/test_service_fixed_breakdown.py`, `tests/debts/test_model_last_payment.py`
Write: `src/sonar/debts/model.py`, `src/sonar/cashflow/service.py`, `tests/debts/test_model_latest_category.py`,
  `tests/cashflow/test_service_fixed_breakdown.py`
Test first: `latest_category` returns the category of the latest categorized matching debit and None without one;
  `load_dashboard` files an unlinked debt with Loans & Installments debits under that group.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts/test_model_latest_category.py tests/cashflow/test_service_fixed_breakdown.py`
- C2 [review] model tests cover: latest of several, an uncategorized latest debit skipped, credits and non-matching
  debits ignored, same-date tie, no match gives None
- C3 [review] a service test shows a manual payment added with "Subscriptions" in the Subscriptions group, an
  unlinked debt with categorized debits in "Loans & Installments", an unlinked debt with uncategorized debits still
  by kind, and a linked debt still labelled by its payment; the existing test is unchanged
- C4 [review] `latest_category` is pure (no DB, no `date.today()`); `load_payoff` totals are unchanged
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 category in Fixed payments forms
Do: Add a "Category" select to the add form and to the edit form of manual payments on the Fixed payments page,
  with "None" plus `fixed_category_names(conn)`, using the `field` macro's `options`
  (`src/sonar/web/templates/components/field.html:7`). The add route stores it via `add_manual`, the edit route via
  `set_category`; a 400 re-render keeps the chosen value. Rebuild and commit `sonar.css`.
Context: D4 detected rows get no select and keep their badge (`src/sonar/web/templates/recurring.html:90-91`); a
  stale non-fixed value preselects None. D2 an unknown or non-fixed submitted name is a 400 re-render storing
  nothing; the edit route ignores `category` for a detected payment. Routes `src/sonar/web/pages/recurring.py:96-166`
  (add passes None at `:128`); forms `recurring.html:122-130` (edit) and `:184` (`#add-payment`). Select ids:
  `field-category` (add), `edit-category-<uid>` (edit). No inline style.
Read: `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`,
  `src/sonar/web/templates/components/field.html`, `tests/html.py`, `tests/web/test_recurring_page.py:1-120`
Write: `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`,
  `src/sonar/web/static/sonar.css`, `tests/web/test_recurring_page_category.py`
Test first: posting the add form with category Subscriptions shows the new row with that category and the API
  lists it; the edit form of a detected payment has no category select.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_recurring_page_category.py tests/web/test_recurring_page.py tests/web/test_recurring_page_errors.py`
- C2 [review] page tests, on ids and `data-*` through `tests/html.py`, cover: add with and without a category, edit
  set and clear on a manual payment, options are None plus only fixed names, the current value preselected, a bad
  name 400 with the value kept and nothing stored, no select on a detected row
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-n04.css" --minify && cmp "$TMPDIR/plz-n04.css" src/sonar/web/static/sonar.css`
  shows the tree's `sonar.css` is the fresh build
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 visual check
Do: gate, pre-authorized (D7). Run `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`,
  then start the app per config `visual_recipe` on `$TMPDIR/sonar-visual.db`. Import the newest file in `samples/`
  on /import, then on /settings set salary day 26 and a balance as of the sample's last booking date. On /recurring
  add a manual payment with category Subscriptions, open its edit drawer, and open a detected payment's drawer.
  Check /recurring and / at desktop and 375px, light and dark (read_page first, scaled screenshots only where layout
  matters), then stop the app.
Done when:
- C1 [visual] the add form shows a Category select of None plus fixed categories; the new payment's row shows the
  Subscriptions badge and its edit drawer preselects Subscriptions
- C2 [visual] a detected payment's edit drawer has no category select
- C3 [visual] on / the breakdown lists the new payment inside the Subscriptions group and matches
  `GET /api/dashboard` `fixed_breakdown`; no unlinked debt with categorized debits sits under Installments or Loans
- C4 [visual] at 375px nothing on either page is cut off or overflows; light and dark are both readable

## N06 plan acceptance
Do: Whole-plan check: run the full verify, then confirm SPEC §11 (acceptance checklist) and §12 (UI) still hold for
  the Fixed payments page and the dashboard, and that the new §13 bullet matches the code.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [review] SPEC §11 items touching Fixed payments and the dashboard (`SPEC.md:162-177`) still hold; detected
  payments still take their category from bookings and Fixed costs totals are unchanged
- C3 [review] SPEC §12 UI rules hold: `base.html` page, `components/` macros, no inline `<style>`, page tests on ids
  and `data-*`, `sonar.css` rebuilt and committed
- C4 [review] the §13 "Manual payment categories" bullet matches `api/recurring.py`, `pages/recurring.py`,
  `service.py` and `debts/model.py`, including D1-D6, and the AGENTS.md endpoint table lists `category`
- C5 [review] no new file in `src/sonar/migrations/` (D1)

## Log

### N01 try 1 · 2026-11-03
check: PASS 5/5

### N03 try 1 · 2026-11-03
exec: BLOCKED · Verify fails outside Write: missing categorization.store.fixed_category_names and E501 in recurring/web category tests; N03 targeted tests: 12 passed

### N02 try 1 · 2026-11-03
exec: DONE · 2152 tests passed; ruff check and format clean
- Added fixed-category lookup, manual-only category setter, and validated recurring POST/PUT category support with tests.
- Documented exact-name validation, omit/clear semantics, and the debt breakdown label override in SPEC §13 and AGENTS.md.
check: PASS 2/2

### N03 replan 1 · 2026-11-03
plan: REPLANNED
- Cause: N02 and N03 ran in the same wave on one tree; the full verify failed on N02's in-flight files, not on N03
- N03 now depends on N02 and N04 on N02,N03, so no exec node runs beside another; brief gains one Context line that tree changes in its Write set are its own

### N02 try 1 · 2026-11-03
verify: PASS
