# Recurring payment descriptions and API
status: RUNNING
created: 2026-10-06 · updated: 2026-10-06
goal: Recurring payments carry an optional description, shown and edited on the Recurring page, and a bearer-protected JSON API lists them and sets their name and description.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: Each recurring payment can hold a short free-text note that explains what it is, and Claude Code can read every payment and set its name and note through the JSON API on both the local app and production, the same way it already manages categories and rules.

In scope: a new migration with a nullable `description` column on `recurring_payments`; the recurring store reading and writing it; the Recurring page showing it as a muted line under the name, with a description field in the add form and in each row's edit form; `GET /api/recurring` and `PUT /api/recurring/{id}` behind the existing `/api` auth; the AGENTS.md endpoint table and a SPEC §13 amendment; a rebuilt `sonar.css`.

Out of scope: the dashboard, the forecasts and every other page; bulk endpoints; the API changing a schedule, category or status; writing the real insurance names (the orchestrator does that through the API after the plan).

Constraints: AGENTS.md rules: strict TDD, pure core and thin store, page tests on stable hooks via `tests/html.py`, money in integer cents, `tests/test_architecture.py`, ruff clean. Hand-entered descriptions survive upgrades and re-detection. Decisions D1-D8 below. No visual gate: the owner checks the page after the plan (D7).

Definition of done: the plan `verify` passes; both endpoints answer correctly against a temp DB in a smoke curl; the owner checks the Recurring page later (no visual gate, D7); after the N02 commit the orchestrator pushes `main` once so CI deploys to production (owner pre-authorized, D8).

## Decisions

- D1 Description storage: migration `0010_recurring_description.sql` adds `description TEXT` (nullable, no default) to `recurring_payments`; input is stripped, and an empty value is stored as NULL; no length cap | confirmed
- D2 Locks: setting a description locks nothing; a name change locks the name exactly as the UI edit does (`src/sonar/recurring/store.py:93`); the schedule is never touched by the API | confirmed
- D3 Re-detection: `sync_detected` never writes `description`, and a detected row that stops being detected is kept, not deleted, when it has a description (`src/sonar/recurring/store.py:181`) | confirmed
- D4 GET shape: `GET /api/recurring` returns a bare JSON list like `GET /api/categories`, active and dismissed payments both, each `{id, detection_key, name, description, category, status, amount_cents, interval_months, day}` from the latest period; money as integer cents | confirmed
- D5 PUT semantics: body `name` and/or `description` (other keys 422 via the strict model); an omitted key is unchanged; `description` null or blank clears it; a blank `name` answers 400 `{"error", "field": "name"}`; unknown id 404; 200 returns the updated item in the GET shape | confirmed
- D6 SPEC: add one §13 amendment line "Recurring descriptions (§6)" stating D1-D5 | confirmed
- D7 Visual gate: no gate node; the owner checks the Recurring page later, waiving the AGENTS.md gate for this plan | confirmed
- D8 Push: header `push: none`; after the N02 commit the orchestrator runs `git push origin main` once, pre-authorized by the owner | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | description column, store and Recurring page | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N02 | recurring JSON API and docs | exec | N01 | sonnet/sonnet | 0 | 0 | TODO | |

## N01 description column, store and Recurring page
Do: Add a nullable `description` to recurring payments: a new migration, the store reading and writing it, and the Recurring page showing it under the name and editing it in the add and edit forms. Add the two store functions the API node needs. Rebuild `sonar.css`.
Context: D1 migration `src/sonar/migrations/0010_recurring_description.sql` adds `description TEXT`; never edit 0003. Strip input; blank is stored as NULL; no cap.
  D2 a description change locks nothing; a name change locks the name (`src/sonar/recurring/store.py:93`).
  D3 `sync_detected` (`src/sonar/recurring/store.py:147`) never writes `description`; the delete of vanished rows at `:181` also skips rows with a description.
  Store: `RecurringPayment` (`:30`) gains `description: str | None`; `_PAYMENT_COLUMNS` (`:20`) and `_payment_from_row` (`:246`) read it; `add_manual` (`:55`) and `edit_payment` (`:73`) take a `description`. Add `get_payment(conn, id)` (raises `PaymentNotFound`) and `update_details(conn, id, name, description)`: sets both, locks the name only if it changed, never touches periods, raises `PaymentNotFound`.
  Page: `src/sonar/web/pages/recurring.py:73` and `:110` take an optional `description` form field and echo it back in the 400 re-render values. Template `src/sonar/web/templates/recurring.html:67`: when set, a muted line under the name with hook `data-field="description"`; `:106` edit form and `:169` add form get an optional `description` field via the `field` macro (unique id per row, like `edit-name-<uid>`). No inline style.
  Rebuild CSS: `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify` (pre-authorized).
Read: `src/sonar/recurring/store.py`, `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`, `tests/recurring/test_store.py`, `tests/recurring/test_store_sync.py`, `tests/web/test_recurring_page.py`, `tests/html.py`
Write: `src/sonar/migrations/0010_recurring_description.sql`, `src/sonar/recurring/store.py`, `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`, `src/sonar/web/static/sonar.css`, `tests/recurring/**`, `tests/web/test_recurring_page.py`, `tests/web/test_recurring_page_errors.py`
Test first: a store test that `update_details` sets a description, leaves `name_locked` false when the name is unchanged and keeps the periods; then a page test that a description posted with the add form shows under `[data-field=description]`.
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring tests/web/test_recurring_page.py tests/web/test_recurring_page_errors.py`
- C2 [review] Store tests cover: add and edit store and clear a description (blank becomes NULL); `update_details` locks the name only on a real change, never touches periods, raises `PaymentNotFound` on an unknown id; `get_payment` returns the payment or raises.
- C3 [review] Sync tests cover: re-detection keeps a description, and a vanished detected row with a description is kept while one without is still deleted.
- C4 [review] Page tests via `tests/html.py`: description shown under the name only when set; add and edit forms save it; the edit form is prefilled with it; a 400 re-render keeps the typed description.
- C5 [review] Migration 0010 only adds the nullable column; 0001-0009 are unchanged in `git diff`; `sonar.css` is rebuilt, not hand-edited.
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 recurring JSON API and docs
Do: Add `GET /api/recurring` and `PUT /api/recurring/{id}` to the existing `/api` router, document them in the AGENTS.md endpoint table, and add a SPEC §13 amendment. Auth needs no new code: the `/api` gate in `src/sonar/web/access.py:39` already covers them.
Context: D4 GET returns a bare list like `src/sonar/web/api.py:129`, active and dismissed (`list_payments(conn, include_dismissed=True)`), each item `{id, detection_key, name, description, category, status, amount_cents, interval_months, day}` from the latest period (periods are ordered by `starts_on`, so `periods[-1]`). Money stays integer cents.
  D5 PUT body via a new `RecurringIn(_StrictModel)` (`src/sonar/web/api.py:42`) and `_parse_body` (`:92`): `name` and/or `description`; an omitted key keeps the current value (read with `get_payment`); `description` null or blank clears it; a blank name answers 400 `{"error", "field": "name"}`; `PaymentNotFound` answers 404 `{"error": "No such recurring payment: <id>"}`; 200 returns the updated item. Write with `update_details` (N01): a name change locks the name; the schedule is never touched (D2).
  D6 SPEC.md §13 gains one line "Recurring descriptions (§6, API)" stating the column, the page display, both endpoints and D2-D5.
  AGENTS.md table at `AGENTS.md:88`: add `GET /recurring` (-) and `PUT /recurring/{id}` (`name`, `description`) rows. Keep AGENTS.md short.
Read: `src/sonar/web/api.py`, `src/sonar/recurring/store.py`, `tests/web/test_api_categories.py`, `tests/web/test_auth_api_token.py`, `AGENTS.md`, `SPEC.md`
Write: `src/sonar/web/api.py`, `tests/web/test_api_recurring.py`, `AGENTS.md`, `SPEC.md`
Test first: `tests/web/test_api_recurring.py` - PUT a description on a seeded payment, then GET lists it with its name, cents amount, interval and day.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_recurring.py tests/web/test_auth_api_token.py`
- C2 [review] API tests cover: GET shape incl. a dismissed payment; PUT description only (name not locked, periods unchanged); PUT name (name locked); description null clears; blank name 400; unknown key 422; unknown id 404; with sign-in on and a token set, the right bearer reaches PUT and a wrong one gets 401.
- C3 [smoke] Start the app on a temp DB (`$TMPDIR`, never `data/sonar.db`), add a payment through `POST /recurring`, then `curl -s http://127.0.0.1:8000/api/recurring` lists it and `curl -s -X PUT -H 'Content-Type: application/json' -d '{"description":"test note"}' http://127.0.0.1:8000/api/recurring/<id>` returns it with that description; stop the app.
- C4 [review] AGENTS.md has exactly the two new table rows; SPEC.md §13 has the one new amendment line; no real names in either.
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-06
exec: DONE · 1050 passed
- Migration 0010 adds nullable description; store get_payment/update_details, add_manual/edit_payment take description (default None); sync keeps it and no longer deletes described rows
- Recurring page shows description under name (data-field=description) and add/edit forms carry it; sonar.css rebuilt, unchanged (classes already present)
check: PASS 2/2
verify: PASS
