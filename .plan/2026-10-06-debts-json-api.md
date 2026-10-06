# Debts JSON API
status: RUNNING
created: 2026-10-06 · updated: 2026-10-06
goal: Claude Code lists, adds and deletes installments and loans through the bearer-protected JSON API, and an API-added debt closes its payment's open draft for good.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: Claude Code can read every debt with the same status figures the Debts page shows, add an installment or a loan with the page's validation, and delete one, on the local app and on production, the way it already manages categories, rules and recurring payments.

In scope: one debts store function that adds a debt and completes the open drafts of the payments it links to, in one transaction; `GET /api/debts`, `POST /api/debts` and `DELETE /api/debts/{id}` in `web/api.py` behind the existing `/api` auth; tests for both; three rows in the AGENTS.md endpoint table and one SPEC §13 amendment line.

Out of scope: editing a debt; the Debts page, its forms and templates (no template change, so no visual gate); drafts endpoints; amounts as text in the API.

Constraints: AGENTS.md rules: strict TDD, pure core and thin store, routes in `web/api.py`, money in integer cents, `tests/test_architecture.py`, ruff clean. Decisions D1-D8 below.

Definition of done: the plan `verify` passes; a smoke curl run on a temp DB creates an installment, lists it and deletes it; after the last node's commit the orchestrator pushes `main` once so CI deploys to production (D8).

## Decisions

- D1 GET shape: `GET /api/debts` returns a bare list in `list_debts` order (installments, then loans, by name), computed like the page with `debt_overview(conn, today())`; every item has every key, null for the other kind's fields: `id, kind, name, match_field, match_value, rate_cents, total_cents, interval_months, first_payment_date, payments_count, balance_cents, balance_as_of, interest_bp, paid_cents, remaining_cents, payments_remaining, end_date, paid_off, linked_payment_ids`. Dates are ISO strings. A loan's `paid_cents` is its paid-since-statement sum, `remaining_cents` comes from `store.remaining_cents`, `end_date` is the installment end date or the loan payoff date, `payments_remaining` is null for a loan, and `linked_payment_ids` lists the active linked recurring payment ids in ascending order | confirmed
- D2 POST body: a strict model, so an unknown key or a wrong JSON type (for example text for a cents field) is a 422. `kind` must be `installment` or `loan`, else 400 with `field: kind`. Installment needs `name, total_cents, rate_cents, interval_months, first_payment_date, payments_count, match_field, match_value`. Loan needs `name, balance_cents, balance_as_of, rate_cents, match_field, match_value`, and `interest_bp` is optional (null or omitted means linear amortization). Each of these answers 400 `{"error", "field"}`: a missing or null required field; a field of the other kind that is set; a date that is not ISO; and a domain `ValueError`, worded by `forms.friendly` and mapped to its field. Money is integer cents only. 201 returns the item in the D1 shape | confirmed
- D3 Draft closing: a new store function `add_debt_closing_drafts(conn, debt) -> int` in `debts/store.py` first runs `sync_drafts(conn)`, so a qualifying payment the page never drafted gets its row. Then, in one transaction, it inserts the debt and sets `status = 'completed'` on every open draft whose `detection_key` is in `linked_keys(debt, txs)`. That payment is never drafted again, even after the debt is deleted. Only the API uses it: the page's add forms keep `add_debt` | confirmed
- D4 DELETE: `DELETE /api/debts/{id}` answers 200 with the deleted item in the D1 shape (read before deleting), like the categories and rules DELETE routes do. An unknown id answers 404 `{"error": "No such debt: <id>"}`. Drafts are left unchanged, so a completed draft stays completed | confirmed
- D5 Auth: no new code is needed, because the `/api` gate in `src/sonar/web/access.py` already covers the new routes. One test proves that the right bearer reaches POST and a wrong one gets a 401 | confirmed
- D6 SPEC: add one §13 amendment line "Debts API (§7, API)" stating D1-D4 | confirmed
- D7 Visual gate: there is no gate node because no template changes | confirmed
- D8 Push: the header says `push: none`. After the N02 commit the orchestrator runs `git push origin main` once, which the owner pre-authorized | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | add a debt and close its drafts | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N02 | debts JSON API and docs | exec | N01 | sonnet/sonnet | 0 | 0 | TODO | |

## N01 add a debt and close its drafts
Do: Add `add_debt_closing_drafts(conn, debt) -> int` to the debts store. When the API creates a debt that links to a drafted payment, it completes that draft the way the page's "complete draft" does, so the draft disappears and never comes back.
Context: D3: first call `sync_drafts(conn)` (`src/sonar/debts/store.py:103`), so qualifying payments have draft rows. Then, inside one `with conn:`, call `_insert_debt` (`:154`) and run `UPDATE debt_drafts SET status = 'completed' WHERE status = 'open' AND detection_key IN (...)` for the keys from `linked_keys(debt, txs)` (`src/sonar/debts/model.py:217`), with txs from `transactions_with_category(conn)` as at `:109`. Return the new debt id.
  `complete_draft` (`:135`) is the existing "completed, never re-drafted" behavior to mirror. Leave `add_debt` and the page unchanged.
Read: `src/sonar/debts/store.py`, `src/sonar/debts/model.py`, `tests/debts/test_store_drafts.py`
Write: `src/sonar/debts/store.py`, `tests/debts/test_store_drafts.py`
Test first: in `tests/debts/test_store_drafts.py`, use the existing seed helpers. Adding an installment that matches a drafted payment through `add_debt_closing_drafts` leaves no open draft. Deleting that debt and running `sync_drafts` again still yields no draft for that payment.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts`
- C2 [review] Tests cover these cases: a draft that already exists is completed; a qualifying payment with no draft row yet (sync never ran) also ends with a completed row; a debt that links to nothing completes no draft and leaves other open drafts open; deleting the debt does not re-draft the payment.
- C3 [review] The insert and the draft update share one transaction. `add_debt`, `complete_draft` and `src/sonar/web/pages/debts.py` are unchanged in `git diff`.
- C4 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 debts JSON API and docs
Do: Add `GET /api/debts`, `POST /api/debts` and `DELETE /api/debts/{id}` to the `/api` router. Add the three rows to the AGENTS.md endpoint table and one SPEC §13 amendment line.
Context: D1 is the GET shape. Build each item from a `DebtView` returned by `debt_overview(conn, today())` (`src/sonar/debts/store.py:64`), with `remaining_cents(view)` (`:91`). Put the item builder in `src/sonar/web/api.py`, next to `_recurring_item` (`:125`).
  D2 is the POST body. Add a `DebtIn(_StrictModel)` (`src/sonar/web/api.py:49`) with StrictInt for the cents and count fields, and parse it with `_parse_body` (`:104`). Build `Installment`, `Loan` and `MatchRule` (`src/sonar/debts/model.py:25`, `:47`, `:70`). On a domain `ValueError`, answer 400 `{"error": forms.friendly(error), "field": <field>}` (`src/sonar/web/forms.py`). Map the message to the field with a small needle table in `api.py` (for example "total must be positive" maps to `total_cents`; the needles are listed at `forms.py` DOMAIN_ERROR_HINTS). Save with `add_debt_closing_drafts` (N01; D3). 201 returns the new item.
  D4: DELETE answers 200 with the item read before `delete_debt` (`store.py:203`). `DebtNotFound` answers 404 `{"error": "No such debt: <id>"}`.
  D5: auth is already covered by `src/sonar/web/access.py`. D6: add the SPEC.md §13 line "Debts API (§7, API)" after the "Recurring descriptions" line.
  In the AGENTS.md table at `AGENTS.md:101`, add `GET /debts` (-), `POST /debts` (`kind` plus the D2 fields) and `DELETE /debts/{id}` (-). Keep AGENTS.md short.
Read: `src/sonar/web/api.py`, `src/sonar/debts/store.py`, `src/sonar/debts/model.py`, `src/sonar/web/forms.py`, `tests/web/test_api_recurring.py`, `tests/web/test_debts_drafts_page.py`, `AGENTS.md`, `SPEC.md`
Write: `src/sonar/web/api.py`, `tests/web/test_api_debts.py`, `AGENTS.md`, `SPEC.md`
Test first: in `tests/web/test_api_debts.py`, POST an installment in cents, then check that GET lists it in the D1 shape with its status figures.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_debts.py tests/web/test_auth_api_token.py`
- C2 [review] Tests cover all of these:
  - GET returns both kinds with every D1 key and nulls for the other kind; status figures match the page's for seeded payments; `linked_payment_ids` is filled.
  - POST creates an installment and a loan, with and without `interest_bp`. It answers 400 for: a bad `kind`; a missing field; the other kind's field; a non-ISO date; a non-positive total, each with the right `field`. It answers 422 for an unknown key and for text in a cents field.
  - A POST that links to a drafted payment leaves no open draft on `/debts`.
  - DELETE returns the item, and a second DELETE answers 404.
  - The right bearer reaches POST and a wrong one gets a 401.
- C3 [smoke] Start the app on a temp DB (`$TMPDIR`, never `data/sonar.db`). Run `curl -s -X POST -H 'Content-Type: application/json' -d '{"kind":"installment","name":"Smoke TV","total_cents":60000,"rate_cents":5000,"interval_months":1,"first_payment_date":"2026-01-15","payments_count":12,"match_field":"counterparty","match_value":"Smoke Shop"}' http://127.0.0.1:8000/api/debts`. It must answer 201 with an id. Then `curl -s http://127.0.0.1:8000/api/debts` lists that debt, and `curl -s -X DELETE http://127.0.0.1:8000/api/debts/<id>` returns it. Stop the app.
- C4 [review] AGENTS.md has exactly the three new table rows. SPEC.md §13 has the one new line. Neither contains real names.
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-06
exec: DONE · 1063 passed
- add_debt_closing_drafts in debts/store.py: sync_drafts, then insert + complete linked open drafts in one transaction
- 4 tests in test_store_drafts.py cover existing draft, no draft row yet, no links, delete does not re-draft
check: PASS 2/2
verify: PASS
