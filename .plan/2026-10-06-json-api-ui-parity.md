# JSON API parity with the pages
status: RUNNING
created: 2026-10-06 · updated: 2026-10-06
goal: Every read and write a Sonar page offers (except file import) is also available as a JSON endpoint under the bearer-protected /api, reusing the page's own functions.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: the owner and Claude Code can query and edit all of Sonar's data from the shell, without a browser. For every page route that reads or writes data there is a JSON endpoint under `/api` that does the same thing through the same store or service function and answers JSON. Bad input answers a 4xx JSON error in the style the existing endpoints already use.

In scope: splitting `src/sonar/web/api.py` into a package with one module per area. The recurring payment item gains the figures the Fixed payments page shows. Recurring payments get add, schedule edit, pause and resume endpoints. Debt drafts get list and complete endpoints, and a debt can be edited in place. A dismissed payment can be restored. Settings and the current balance get read and write endpoints, and there is a rules reapply endpoint. Read-only endpoints cover the dashboard, Keep the lights on, the Monthly page and a transaction list filterable by date range, category, uncategorized and search text. The lights-on and monthly page logic moves into shared loaders so the page and the API do not duplicate it. Docs: the AGENTS.md endpoint table and one SPEC §13 amendment.

Out of scope: import through the API, auth changes, template and CSS changes, and migrations. The recurring dismiss endpoint already exists from plan 2026-10-06-debt-links-keep-base-key and is moved, not rebuilt.

Constraints: AGENTS.md rules: strict TDD with tests in `tests/web/` (plus `tests/cashflow/`, `tests/recurring/` and `tests/debts/` for moved logic and the two new store functions), anonymized fixtures, functional core and thin shell, integer cents, ISO dates, `tests/test_architecture.py`, ruff clean. Every existing page test passes unchanged. Decisions D1-D11.

Definition of done: each page data route maps to a tested `/api` endpoint (file import excepted), plus the D6 extras; the AGENTS.md table and SPEC §13 are updated; the full `verify` passes; a smoke run on a temp DB exercises every new endpoint.

## Decisions

- D1 Split `src/sonar/web/api.py` into a package `src/sonar/web/api/`, because the file is 583 lines and this plan roughly doubles it. The package holds `__init__.py` (`build_api_router(db_path, today)` creates the `/api` router and includes each module's router), `_common.py` (`_StrictModel`, `_numeric_as_text`, `_parse_body`), `categories.py` (categories, rules, uncategorized), `recurring.py` and `debts.py`. Later nodes add `settings.py` and `cashflow.py`. `app.py`'s import stays as it is. The AGENTS.md Layout line changes `api.py` to `api/` | confirmed
- D2 Errors and auth stay as they are now. A body goes through `_parse_body`: a wrong content type is a 415, and bad JSON, an unknown key or a wrong JSON type is a 422. A validation failure is a 400 `{"error", "field"}`, worded by `forms.friendly`. An unknown id is a 404 `{"error": "No such <thing>: <id>"}`. A bad query parameter is a 400 `{"error", "field"}`. The existing `/api` gate covers auth, so there is no auth code | confirmed
- D3 The recurring item (every recurring response) gains these keys: `source`, `last_paid_date`, `next_due` (from `next_due_date(periods, last_paid_date, today())`, as on the page), `until` (from the latest period), `periods` (a list of `{starts_on, until, amount_cents, interval_months, day}`), and `debt_id` (the id of the debt that links the payment, else null, inverted from `debt_overview` the way the page does). Dates are ISO | confirmed
- D4 Recurring writes, all of which answer with the recurring item: `POST /api/recurring` takes `name` (required, trimmed, not blank), `amount_cents`, `interval_months`, `day` and `starts_on` (all required), and an optional `description`. It calls `add_manual` with category null and answers 201. `PUT /api/recurring/{id}` also accepts `amount_cents`, `interval_months` and `day`. A missing key keeps the latest period's value. When any of the three is present it calls `edit_payment` with the merged values; otherwise it keeps today's `update_details` path. `POST /api/recurring/{id}/pause` takes `{last_date}` and calls `pause_payment`. `POST /api/recurring/{id}/resume` takes `starts_on`, `amount_cents` and `interval_months`, plus an optional `day` that defaults to `starts_on.day`, and calls `resume_payment`. Ints are StrictInt and dates are ISO text | confirmed
- D5 Debt drafts: `GET /api/debts/drafts` returns `sync_drafts(conn)` as `[{id, detection_key, name, rate_cents, interval_months, first_payment_date, match_field, match_value}]`. `POST /api/debts/drafts/{id}` takes the `POST /api/debts` body. It validates the body with `_build_debt`, then calls `complete_draft` and answers 201 with the debt item. A `DraftNotFound` (an unknown or already completed draft) answers 404 `{"error": "No such draft: <id>"}`. | confirmed
- D6 Three extras beyond the pages: (a) `PUT /api/debts/{id}` takes the `POST /api/debts` body and validation (`_build_debt`), replaces that debt in place (kind may change; the other kind's columns become NULL) through a new store function `update_debt(conn, id, debt)`, answers 200 with the debt item, 404 `{"error": "No such debt: <id>"}` for an unknown id, and leaves drafts untouched; (b) `POST /api/recurring/{id}/restore` undoes a dismiss through a new store function `restore(conn, id)` that sets status back to `active`, answers 200 with the recurring item, 404 for an unknown id, and 409 `{"error": "Recurring payment <id> is not dismissed"}` when it is not dismissed; (c) `GET /api/transactions` takes `q`, a case-insensitive substring match over counterparty and purpose, combinable with the other filters. Still not built: file import and the uncategorized page's `request_text`; `GET /api/transactions?uncategorized=true` covers that page's list | confirmed
- D7 Settings: `GET /api/settings` returns `{salary_day, overdraft_limit_cents, balance}`, where `balance` is `{amount_cents, as_of, source}` or null. `PUT /api/settings` takes `salary_day` and `overdraft_limit_cents`, both optional StrictInt; a missing key keeps the stored value. If no salary day is stored and none is sent, it answers 400 with field `salary_day`. It calls `save_settings`. `POST /api/settings/balance` takes `amount_cents` (any sign) and `as_of` (ISO, required, as on the page). It calls `set_manual_balance(conn, as_of, amount_cents, today())`; a future date answers 400 with field `as_of`. Both writes answer 200 with the GET shape. | confirmed
- D8 `POST /api/reapply` (no body) calls `reapply_stored_taxonomy(conn, today())` and answers `{"uncategorized": <count>}`, like the Uncategorized page's Reapply button | confirmed
- D9 Dashboard and lights-on: `GET /api/dashboard` returns `load_dashboard(...)` field by field, through a recursive `_jsonable` in `_common.py`: a dataclass becomes an object, a date ISO text, a tuple or list a list. `debts` becomes `[{name, remaining_cents}]`. `GET /api/lights-on` returns `{categories, salary_months, daily, months}`, where `daily` is the one-day `LightsOnForecast` or null, and `months` is the page's table rows (per-day cents; the last 24 months). To share that logic, the page's row building moves into a pure `month_rows` in `src/sonar/cashflow/lights_on.py`, and its loading into `load_lights_on` in `src/sonar/cashflow/service.py`. The page then calls both. There is no template change. | confirmed
- D10 Monthly and transactions: The Monthly page's loading moves into `load_monthly(conn, category_types, today, month)` in `src/sonar/cashflow/service.py`, which the page and the API share. `GET /api/monthly?month=YYYY-MM&category=` returns `{month, start, end, salary_months, months, older, newer, spent_cents, transfers_net_cents, groups, by_category, transfer_totals, payments}`. `payments` is narrowed by `only_category` as on the page. A bad `month` answers 400 with field `month`; the page keeps its 404. `GET /api/transactions?from=&to=&category=&uncategorized=` returns transactions newest first. `from` and `to` are inclusive ISO booking dates; `category` is an exact name; `uncategorized=true` returns only uncategorized ones. Sending `category` and `uncategorized` together, or a bad date, answers 400. The transaction item is `{booking_date, value_date, amount_cents, currency, counterparty, purpose, account, iban, mandate_ref, creditor_id, category}`, without `raw_row`. | confirmed
- D11 Docs and gate: one N08 docs node, after every endpoint exists, adds the AGENTS.md table rows and one SPEC §13 bullet "API parity (§4-§9, API)". No template changes, so there is no visual gate and no CSS rebuild | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/haiku | 1 | 0 | DONE | |
| N02 | split api into a package | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | recurring writes, restore and item | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | debt drafts and edit API | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N05 | settings and reapply API | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N06 | dashboard and lights-on API | exec | N05 | sonnet/sonnet | 1 | 0 | RUNNING | |
| N07 | monthly and transactions API | exec | N06 | sonnet/sonnet | 0 | 0 | TODO | |
| N08 | API parity docs | exec | N03,N04,N07 | haiku/sonnet | 0 | 0 | TODO | |
| N09 | plan acceptance | check | N08 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point. Plan 2026-10-06-debt-links-keep-base-key is done, so `POST /api/recurring/{id}/dismiss` exists, and the untouched tree passes the plan verify. The repo is writable for the per-node commits.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `.planzilla/plz status 2026-10-06-debt-links-keep-base-key | head -1 | grep -q DONE`
- C3 [cmd] `grep -q 'recurring/{id}/dismiss' src/sonar/web/api.py`
- C4 [cmd] `test -w .git && git rev-parse --abbrev-ref HEAD`

## N02 split api into a package
Do: Replace `src/sonar/web/api.py` with the package `src/sonar/web/api/`, moving the code without changing any behavior. This lets later nodes add endpoints in separate modules.
Context: D1:
  - `__init__.py`: `build_api_router(db_path, today)`, the only public name `app.py` imports (`src/sonar/web/app.py:27`). It creates `APIRouter(prefix="/api")` and includes each module's `build_router(db_path, today)`.
  - `_common.py`: `_JSON_CONTENT_TYPE`, `_StrictModel`, `_numeric_as_text`, `_parse_body`.
  - `categories.py`: CategoryIn, RuleIn, MoveIn and the categories, rules and uncategorized routes.
  - `recurring.py`: RecurringIn, `_recurring_item` and the recurring routes, including dismiss.
  - `debts.py`: DebtIn, the debt constants, `_debt_item`, `_build_debt`, `_find_debt` and the debt routes.
  Keep the route order inside each module. Rewrite the module docstring to describe the package. In AGENTS.md's Layout section, change `` `api.py` `` in the `src/sonar/web/` line to `` `api/` (one module per area) ``.
  This is a pure move: no route, status code, JSON shape or error text changes, and no test changes except import paths, if any test imports from `sonar.web.api`.
Read: `src/sonar/web/api.py`, `src/sonar/web/app.py:20-30,105-115`, `tests/test_architecture.py`, `AGENTS.md:15-25`
Write: `src/sonar/web/api.py`, `src/sonar/web/api/**`, `AGENTS.md`, `tests/web/test_api_*.py`
Test first: - (pure move; the existing `tests/web/test_api_*.py` and `tests/web/test_auth_api_token.py` prove it)
Done when:
- C1 [cmd] `test ! -e src/sonar/web/api.py && test -f src/sonar/web/api/__init__.py && test -f src/sonar/web/api/_common.py`
- C2 [cmd] `uv run pytest -q tests/web tests/test_architecture.py`
- C3 [review] `git diff --stat tests/` shows at most import-line changes. The package modules hold the routes named in Context, and every moved function body is unchanged. The AGENTS.md diff is the one Layout line.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 recurring writes, restore and item
Do: Make the JSON API do everything the Fixed payments page does with a recurring payment. Every recurring response shows the page's figures, and there are add, schedule-edit, pause, resume and restore endpoints, all in `src/sonar/web/api/recurring.py`. Restore needs a new store function.
Context: The page routes to mirror are in `src/sonar/web/pages/recurring.py`: add `:73`, edit `:112`, pause `:156`, resume `:183`, and the row figures `:39-59`.
  D3, the item: `_recurring_item` gains `source`, `last_paid_date`, `next_due`, `until` (the latest period's), `periods` (a list of `{starts_on, until, amount_cents, interval_months, day}`) and `debt_id`. `next_due` is `next_due_date(p.periods, p.last_paid_date, today())`. `debt_id` is the debt that links the payment in `debt_overview(conn, today())`, else null. Dates are ISO or null. The function then needs `today` and a payment-id to debt-id map: build the map once per request.
  D4, the endpoints. Every write uses the page's store function, and each answers with the item (POST 201, others 200).
  - `POST /api/recurring` takes `name`, `amount_cents`, `interval_months`, `day` and `starts_on` (all required), and an optional `description`. It calls `add_manual(conn, name.strip(), None, SchedulePeriod(...), description)`.
  - `PUT /api/recurring/{id}` adds optional `amount_cents`, `interval_months` and `day`. A missing key keeps the latest period's value. If any of the three is present, it calls `edit_payment` with the merged values. Otherwise it keeps the existing `update_details` path, so the existing PUT tests still pass.
  - `POST /{id}/pause` takes `{last_date}` and calls `pause_payment`.
  - `POST /{id}/resume` takes `starts_on`, `amount_cents` and `interval_months`, plus an optional `day` that defaults to `starts_on.day` (as at `pages/recurring.py:197`). It calls `resume_payment`.
  D6b: add `restore(conn, id)` to `src/sonar/recurring/store.py` beside `dismiss` (`:155`): in one `with conn:`, `_require_exists`, raise a new `NotDismissed(ValueError)` unless status is `dismissed`, then set status `active`. `POST /api/recurring/{id}/restore` (no body) answers 200 with the item, 404 on `PaymentNotFound`, 409 `{"error": "Recurring payment <id> is not dismissed"}` on `NotDismissed`.
  Body models are `_StrictModel` subclasses, with StrictInt for ints and StrictStr for text and dates.
  D2, errors:
  - A missing required key, or a blank `name`, answers 400 `{"error": "<key> is required", "field": <key>}`.
  - A non-ISO date answers 400 with the date field.
  - A `SchedulePeriod` ValueError (`src/sonar/recurring/schedule.py:28-34`) answers 400 with `friendly(error)`. A needle table maps its field: "amount must be positive" to `amount_cents`, "interval must be at least" to `interval_months`, "day must be within" to `day`.
  - Validate by building a `SchedulePeriod`; for an edit, use the latest period's `starts_on`.
  - `PaymentNotFound` answers 404 `{"error": "No such recurring payment: <id>"}`.
Read: `src/sonar/web/api/recurring.py`, `src/sonar/web/api/_common.py`, `src/sonar/web/pages/recurring.py`, `src/sonar/recurring/store.py:44-180`, `src/sonar/recurring/schedule.py:20-100`, `src/sonar/web/forms.py:36-62`, `tests/web/test_api_recurring.py`
Write: `src/sonar/web/api/recurring.py`, `src/sonar/recurring/store.py`, `tests/recurring/test_store.py`, `tests/web/test_api_recurring.py`
Test first: `POST /api/recurring` with a valid body answers 201, and `GET /api/recurring` lists it with `next_due`, `periods` and `debt_id: null`.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_recurring.py`
- C2 [review] Tests cover:
  - POST 201, plus a 400 for a missing key, a blank name, a bad date, `amount_cents: 0` and `day: 32`, and a 422 for text in `amount_cents`.
  - PUT changing only `amount_cents` locks the schedule and changes only that period value.
  - pause sets `until`.
  - resume adds a period, and `day` defaults to `starts_on.day`.
  - 404 on pause, resume and PUT for an unknown id.
  - `debt_id` is set for a payment a seeded debt links.
  - `restore` in `tests/recurring/test_store.py`: a dismissed payment becomes active and listed again; an active one raises `NotDismissed`; an unknown id raises `PaymentNotFound`. The API restore answers 200, 409 and 404 for the same cases.
- C3 [review] The routes call `add_manual`, `edit_payment`, `update_details`, `pause_payment`, `resume_payment` and `restore` and contain no SQL. In `src/sonar/recurring/` only `restore` and `NotDismissed` are added; `src/sonar/web/pages/` and the templates are unchanged.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 debt drafts and edit API
Do: Add `GET /api/debts/drafts` and `POST /api/debts/drafts/{id}` to `src/sonar/web/api/debts.py`, mirroring the Debts page's open drafts and its "complete draft" forms. Add `PUT /api/debts/{id}`, which edits a debt in place through a new store function.
Context: D5: GET returns `sync_drafts(conn)` (`src/sonar/debts/store.py:103`) in its order, each as `{id, detection_key, name, rate_cents, interval_months, first_payment_date, match_field, match_value}`. The fields come from `draft.prefill` (`src/sonar/debts/drafts.py:24`); dates are ISO.
  POST takes the same `DebtIn` body as `POST /api/debts`. It reuses `_build_debt` for every 400, then calls `complete_draft(conn, id, debt)` (`store.py:135`), as the page does (`src/sonar/web/pages/debts.py:171-194`). It answers 201 with `_debt_item(_find_debt(conn, new_id))`. `DraftNotFound` (an unknown or already completed draft) answers 404 `{"error": "No such draft: <id>"}`. Validate before touching the DB, so a bad body for an unknown draft answers 400.
  D6a: add `update_debt(conn, id, debt) -> None` to `src/sonar/debts/store.py` beside `delete_debt` (`:222`). In one `with conn:` it raises `DebtNotFound` for an unknown id, else UPDATEs every column of that row: `kind`, the shared columns and both kinds' columns, with the other kind's columns set to NULL (mirror `_insert_debt`, `:173`). `PUT /api/debts/{id}` takes the `DebtIn` body, validates it with `_build_debt` first (400s as POST), calls `update_debt`, answers 200 with `_debt_item(_find_debt(conn, id))`, and answers 404 `{"error": "No such debt: <id>"}` on `DebtNotFound`. Drafts are left untouched.
  D2 error shapes as for `POST /api/debts`. Register the routes in the module's router. A GET on `/debts/drafts` must not clash with the existing `DELETE /debts/{id}`.
Read: `src/sonar/web/api/debts.py`, `src/sonar/debts/store.py:55-147`, `src/sonar/debts/drafts.py:1-60`, `src/sonar/web/pages/debts.py`, `tests/web/test_api_debts.py`, `tests/web/test_debts_drafts_page.py`
Write: `src/sonar/web/api/debts.py`, `src/sonar/debts/store.py`, `tests/debts/test_store.py`, `tests/web/test_api_debt_drafts.py`, `tests/web/test_api_debts.py`
Test first: when a seeded debt-category payment qualifies for a draft, `GET /api/debts/drafts` lists it with its prefill, and a valid POST of an installment for that draft answers 201, after which GET no longer lists it.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_debt_drafts.py tests/web/test_api_debts.py`
- C2 [review] Tests cover:
  - The GET item keys.
  - Completing a draft as a loan and as an installment.
  - A second POST on the same draft answers 404, and so does an unknown id.
  - A bad body answers 400 with `field`.
  - With sign-in on, the right bearer reaches POST and a wrong one gets a 401.
  - `update_debt` in `tests/debts/test_store.py`: an installment edited in place keeps its id; an installment changed to a loan leaves the installment columns NULL; an unknown id raises `DebtNotFound`.
  - In `tests/web/test_api_debts.py`, PUT answers 200 with the new values and the same id; there is a 400 with `field` for a bad body and a 404 for an unknown id.
- C3 [review] The routes call `sync_drafts`, `complete_draft` and `update_debt` and contain no SQL. In `src/sonar/debts/` only `update_debt` is added, and the pages are unchanged.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 settings and reapply API
Do: Add the Settings page's reads and writes as `src/sonar/web/api/settings.py`, and the Uncategorized page's Reapply action as `POST /api/reapply` in `src/sonar/web/api/categories.py`. Include the new router in `src/sonar/web/api/__init__.py`.
Context: D7:
  - `GET /api/settings` returns `{salary_day, overdraft_limit_cents, balance}`, built from `load_settings` and `current_balance` (`src/sonar/cashflow/store.py:33,83`). `balance` is `{amount_cents, as_of, source}` or null.
  - `PUT /api/settings` takes `{salary_day, overdraft_limit_cents}`, both optional StrictInt. A missing key keeps the stored value. With no salary day stored and none sent, it answers 400 `{"error": "salary_day is required", "field": "salary_day"}`. It then calls `save_settings` (`:44`). A ValueError answers 400 with `friendly(error)`, and the field is mapped by needle: "salary_day" to `salary_day`, "overdraft_limit_cents" to `overdraft_limit_cents`.
  - `POST /api/settings/balance` takes `{amount_cents, as_of}`, both required; `amount_cents` is a StrictInt of any sign and `as_of` is ISO text. It calls `set_manual_balance(conn, as_of, amount_cents, today())` (`:64`). A non-ISO or future date answers 400 with field `as_of`, and a missing key answers 400 with that field.
  - Both writes answer 200 with the GET shape.
  - Mirror `src/sonar/web/pages/settings.py:43-105`.
  D8: `POST /api/reapply` takes no body. It calls `reapply_stored_taxonomy(conn, today())` (`src/sonar/categorization/service.py:88`) and answers `{"uncategorized": <count>}`, as `src/sonar/web/pages/uncategorized.py:43` does.
  D2 errors.
Read: `src/sonar/web/api/__init__.py`, `src/sonar/web/api/_common.py`, `src/sonar/web/api/categories.py`, `src/sonar/web/pages/settings.py`, `src/sonar/cashflow/store.py:20-95`, `tests/web/test_settings_page.py`, `tests/web/test_api_categories.py:1-40`
Write: `src/sonar/web/api/settings.py`, `src/sonar/web/api/__init__.py`, `src/sonar/web/api/categories.py`, `tests/web/test_api_settings.py`, `tests/web/test_api_reapply.py`
Test first: `PUT /api/settings` with `{"salary_day": 25}` on a fresh DB answers 200, and GET then shows salary day 25 with the default overdraft limit.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_settings.py tests/web/test_api_reapply.py`
- C2 [review] Tests cover:
  - GET with no balance (null) and with a manual balance.
  - A partial PUT keeps the other value.
  - A 400 for salary day 0 and 32, a positive overdraft limit, and a missing salary day on a fresh DB.
  - The balance POST, including a negative amount; a future `as_of` answers 400 and a missing key answers 400.
  - A 422 for text in an int.
  - Reapply categorizes a transaction after a rule is inserted straight into the store and returns the new count.
  - One bearer/401 test.
- C3 [review] The routes call `save_settings`, `set_manual_balance` and `reapply_stored_taxonomy` and contain no SQL; the pages and `src/sonar/cashflow/` are unchanged.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 dashboard and lights-on API
Do: Add `GET /api/dashboard` and `GET /api/lights-on` in a new `src/sonar/web/api/cashflow.py`. First move the lights-on page's data logic into the cashflow package, so the page and the API share it.
Context: D9:
  - Add `month_rows(months, categories, used) -> tuple[MonthRow, ...]` to `src/sonar/cashflow/lights_on.py`. It is pure. `MonthRow` is a frozen dataclass with `period`, `used`, `total_cents`, `by_category` and `occasional_cents`. It replaces `_lights_on_table_rows` and `_cents` in `src/sonar/web/pages/lights_on.py:24-43`, rounding with the module's own `_cents` (`lights_on.py:177`).
  - Add `load_lights_on(conn, category_types) -> LightsOnView` to `src/sonar/cashflow/service.py`, holding `categories`, `months` (the last 24), `daily` and `salary_months`. It is the page's loading from `pages/lights_on.py:77-95`.
  - The page calls both. The template reads the same keys (Jinja resolves `row.x` on a dataclass), so the template does not change. `_lights_on_chart_series` stays in the page.
  - `_jsonable(value)` goes in `src/sonar/web/api/_common.py`. A dataclass becomes a dict of its fields, recursively; a date becomes ISO text; a tuple or list becomes a list; a dict keeps its keys; other values pass through.
  - `GET /api/dashboard` returns `_jsonable(load_dashboard(conn, load_stored_taxonomy(conn).categories, today()))`, as `src/sonar/web/pages/dashboard.py:23-28` does, with `debts` replaced by `[{name, remaining_cents}]`.
  - `GET /api/lights-on` returns `{categories, salary_months, daily: _jsonable(daily), months: _jsonable(month_rows(...))}`.
  - Include the router in `src/sonar/web/api/__init__.py`.
Read: `src/sonar/web/pages/lights_on.py`, `src/sonar/web/pages/dashboard.py`, `src/sonar/cashflow/service.py:1-145`, `src/sonar/cashflow/lights_on.py`, `src/sonar/web/api/__init__.py`, `src/sonar/web/api/_common.py`, `tests/web/test_lights_on_page.py`, `tests/cashflow/test_lights_on.py`, `tests/cashflow/test_service.py:1-60`
Write: `src/sonar/cashflow/lights_on.py`, `src/sonar/cashflow/service.py`, `src/sonar/web/pages/lights_on.py`, `src/sonar/web/api/cashflow.py`, `src/sonar/web/api/_common.py`, `src/sonar/web/api/__init__.py`, `tests/cashflow/test_lights_on.py`, `tests/cashflow/test_service.py`, `tests/web/test_api_dashboard.py`, `tests/web/test_api_lights_on.py`
Test first: `month_rows` for one month of known spend gives the expected per-day cents per category, and `GET /api/dashboard` with a salary day, a balance and a manual payment returns `payday`, `due` and `expected_cents` equal to `load_dashboard`'s.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow tests/web/test_api_dashboard.py tests/web/test_api_lights_on.py tests/web/test_lights_on_page.py tests/web/test_dashboard_page.py`
- C2 [review] Tests cover:
  - `month_rows` rounding.
  - `load_lights_on` with no transactions (empty months, daily null).
  - The dashboard JSON with and without a salary day (forecast keys null), with dates ISO and `debts` as objects.
  - The lights-on JSON with data and with none.
- C3 [review] `git diff --stat tests/web/test_lights_on_page.py tests/web/test_dashboard_page.py src/sonar/web/templates` is empty. The page no longer holds the table-row or loading logic; the API and the page call the same functions.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 monthly and transactions API
Do: Add `GET /api/monthly` and `GET /api/transactions` to `src/sonar/web/api/cashflow.py`. First move the Monthly page's loading into the cashflow service, so the page and the API share it.
Context: D10:
  - `load_monthly(conn, category_types, today, month: date | None) -> MonthlyView` in `src/sonar/cashflow/service.py` holds `spending`, `months`, `selected`, `older`, `newer` and `salary_months`. It is `src/sonar/web/pages/monthly.py:36-57`, minus the month parsing.
  - The page keeps parsing `month` and its 404, and keeps `only_category`. The template context keys do not change.
  - `GET /api/monthly?month=YYYY-MM&category=` returns these keys:
    - `month`, `start` and `end`, from `spending.period`.
    - `salary_months`, `months` (ISO list), `older` and `newer`.
    - `spent_cents`, `transfers_net_cents`, and `groups` (`_jsonable`).
    - `by_category` and `transfer_totals`.
    - `payments`, narrowed by `only_category` when `category` is set, as the page does.
  - A bad `month` (`parse_month` ValueError) answers 400 with field `month`.
  - `GET /api/transactions` takes the query params `from`, `to`, `category`, `uncategorized` and `q`. It reads `transactions_with_category(conn)`. `from` and `to` are inclusive bounds on `booking_date`. `category` is an exact match. `uncategorized=true` keeps only rows whose category is None. `q` (D6c) keeps rows whose counterparty or purpose contains it, case-insensitively (`casefold`). All filters combine. The result is sorted newest first by `booking_date`.
  - A bad date, a bad `uncategorized` value, or `category` and `uncategorized` together answers 400 with that field.
  - One `_transaction_item(tx, category)` serves both endpoints: `{booking_date, value_date, amount_cents, currency, counterparty, purpose, account, iban, mandate_ref, creditor_id, category}`, without `raw_row`.
Read: `src/sonar/web/pages/monthly.py`, `src/sonar/cashflow/monthly.py:39-165`, `src/sonar/cashflow/service.py`, `src/sonar/categorization/store.py:374-390`, `src/sonar/transactions.py`, `src/sonar/web/api/cashflow.py`, `tests/web/test_monthly_page.py:1-60`, `tests/cashflow/test_service.py:1-60`
Write: `src/sonar/cashflow/service.py`, `src/sonar/web/pages/monthly.py`, `src/sonar/web/api/cashflow.py`, `tests/cashflow/test_service.py`, `tests/web/test_api_monthly.py`, `tests/web/test_api_transactions.py`
Test first: `GET /api/transactions?from=2026-01-01&to=2026-01-31&uncategorized=true` on seeded anonymized rows returns only January's uncategorized ones, newest first, without `raw_row`.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_service.py tests/web/test_api_monthly.py tests/web/test_api_transactions.py tests/web/test_monthly_page.py`
- C2 [review] Tests cover:
  - `load_monthly` with and without a month.
  - Monthly JSON for the default month, a chosen month and a category filter, plus a 400 for `month=2026-13`.
  - Transactions filtered by range, by category, by uncategorized and by `q` (mixed case, matching purpose only and counterparty only, combined with a range), plus the three 400 cases.
  - One bearer/401 test.
- C3 [review] `git diff --stat tests/web/test_monthly_page.py src/sonar/web/templates` is empty, and the API and the page both call `load_monthly`.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 API parity docs
Do: Document every new endpoint in the AGENTS.md Categorization workflow endpoint table, and add one SPEC §13 amendment bullet.
Context: D11. In `AGENTS.md`, edit the `PUT /recurring/{id}` row's body to read `` `name`, `description`, `amount_cents`, `interval_months`, `day` ``. Add rows in the same style, each after its area's existing rows:
  - POST `/recurring`: `` `name`, `amount_cents`, `interval_months`, `day`, `starts_on`, `description` ``
  - POST `/recurring/{id}/pause`: `` `last_date` ``
  - POST `/recurring/{id}/resume`: `` `starts_on`, `amount_cents`, `interval_months`, `day` ``
  - GET `/debts/drafts`: -
  - POST `/debts/drafts/{id}`: same fields as POST `/debts`
  - GET `/settings`: -
  - PUT `/settings`: `` `salary_day`, `overdraft_limit_cents` ``
  - POST `/settings/balance`: `` `amount_cents`, `as_of` ``
  - POST `/reapply`: -
  - GET `/dashboard`: -
  - GET `/lights-on`: -
  - GET `/monthly`: query `month`, `category`
  - GET `/transactions`: query `from`, `to`, `category`, `uncategorized`, `q`
  - PUT `/debts/{id}`: same fields as POST `/debts` (after the POST `/debts` row)
  - POST `/recurring/{id}/restore`: - (after the dismiss row)
  In `SPEC.md` §13, add one bullet right after the "Debts API (§7, API)" bullet: "API parity (§4-§9, API)". In two or three sentences it says that every page read and write except file import has a `/api` JSON equivalent that uses the page's own functions; it lists the endpoint groups (recurring add/edit/pause/resume/restore, debt edit, debt drafts, settings and balance, reapply, dashboard, lights-on, monthly, transactions); and it notes the 400/404/409/422 error shapes. No real names.
Read: `AGENTS.md:80-115`, `SPEC.md:236-256`
Write: `AGENTS.md`, `SPEC.md`
Test first: -
Done when:
- C1 [cmd] `grep -q '/recurring/{id}/restore' AGENTS.md && grep -q '| PUT | .*/debts/{id}' AGENTS.md && grep -q '/transactions' AGENTS.md && grep -q 'API parity' SPEC.md`
- C2 [review] `git diff AGENTS.md` adds exactly 15 table rows and edits only the PUT recurring row; `git diff SPEC.md` adds one §13 bullet; no other lines change.
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N09 plan acceptance
Do: Check the whole plan against its Definition of done, SPEC §11 and §12, and AGENTS.md's rules.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [review] Walk `src/sonar/web/pages/*.py`. Every data route other than auth, `/import` and `/uncategorized/badge` has an `/api` endpoint with a test, and the D6 extras (`PUT /api/debts/{id}`, `POST /api/recurring/{id}/restore`, `q` on `/api/transactions`) exist with tests.
- C3 [review] Every API write calls the same store or service function as its page route, with no duplicated validation or SQL. Templates, migrations and auth code are unchanged; the only new store functions are `update_debt` and `restore` (`git diff --stat` since N01). `tests/test_architecture.py` passes, and fixtures use no real names, IBANs or ids.
- C4 [smoke] Start the app on a temp DB under `$TMPDIR` (never `data/sonar.db`), then curl each endpoint below. Each answers 2xx JSON, an unknown recurring id answers 404, and a bad month answers 400. Stop the app.
  - `PUT /api/settings`, `POST /api/settings/balance`, `POST /api/recurring`, then pause and resume.
  - `GET /api/dashboard`, `/api/lights-on`, `/api/monthly`, `/api/transactions` and `/api/debts/drafts`.
  - `POST /api/reapply`, `GET /api/transactions?q=...`, then `PUT /api/debts/{id}` on a POSTed debt, and dismiss then restore of the added payment (a second restore answers 409).
- C5 [review] SPEC §11 and §12 still hold, and the AGENTS.md table matches the routes in `src/sonar/web/api/`.

## Log

### N01 try 1 · 2026-10-06
check: PASS 4/4

### N02 try 1 · 2026-10-06
exec: DONE · 1134 passed
- web/api.py split into web/api/ (__init__, _common, categories, recurring, debts); bodies moved unchanged
- each module exposes build_router(db_path, today); __init__ includes them in original route order under /api
- AGENTS.md Layout line now says api/ (one module per area)
check: PASS 3/3
verify: PASS

### N03 try 1 · 2026-10-06
exec: DONE · 1204 passed
- recurring API: item gains page figures and debt_id; POST add, PUT schedule edit, pause, resume, restore; store.restore and NotDismissed
- null schedule keys in PUT count as missing; old PUT unknown-key test now uses a different key since amount_cents is valid
check: PASS 2/2

### N04 try 1 · 2026-10-06
exec: DONE · 1204 passed
- Added GET /api/debts/drafts, POST /api/debts/drafts/{id}, PUT /api/debts/{id} in web/api/debts.py; update_debt in debts/store.py
- Validate body before DB; DraftNotFound -> 404; tests in test_store, test_api_debt_drafts, test_api_debts

### N03 try 1 · 2026-10-06
verify: PASS

### N05 try 1 · 2026-10-06
exec: DONE · 1204 passed
- Added web/api/settings.py (GET/PUT /api/settings, POST /api/settings/balance) and POST /api/reapply in categories.py; router included
- Missing balance keys answer 400 with the field; domain ValueErrors map to field by needle; tests in test_api_settings.py and test_api_reapply.py

### N04 try 1 · 2026-10-06
check: PASS 2/2

### N05 try 1 · 2026-10-06
check: PASS 2/2
verify: PASS

### N04 try 1 · 2026-10-06
verify: PASS
