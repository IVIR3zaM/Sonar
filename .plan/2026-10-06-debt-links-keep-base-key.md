# Debt links keep the base key
status: RUNNING
created: 2026-10-06 · updated: 2026-10-06
goal: A debt still links the owner's recurring payment stored under a mandate's unsplit key after that mandate splits into same-day series, so the dashboard never counts it twice; and the JSON API can dismiss a recurring payment.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: since same-day splitting, a debt resolves its matching debits only to split keys (`<base>#n`). When a mandate shared by a loan and unrelated purchases has a date where two debits meet, the group splits, and a recurring payment the owner edited under the bare base key (kept by `sync_detected`) loses its debt link. The dashboard then counts the debt and that payment both. A debt must link payments keyed by the base key of its matching debits as well as the split keys. Separately, the Categorization workflow can only rename or describe a recurring payment through `/api`; it also needs to dismiss one, as the Fixed payments page already can.

In scope: `linked_keys` in `src/sonar/debts/model.py`, which feeds `debt_overview`, `sync_drafts` and `add_debt_closing_drafts` (`src/sonar/debts/store.py:78,111,162`) and through `debt_overview` the dashboard's linked-id exclusion (`src/sonar/cashflow/service.py:175`); `draft_prefill` in `src/sonar/debts/drafts.py`, which has the same base-vs-split mismatch; tests in `tests/debts/`; one sentence added to the SPEC §13 "Same-day series" bullet. A new `POST /api/recurring/{id}/dismiss` in `src/sonar/web/api.py` with tests in `tests/web/test_api_recurring.py`, its row in the AGENTS.md Categorization endpoints table, and a clause in the SPEC §13 "Recurring descriptions" bullet.

Out of scope: other recurring actions (pause, resume, add) in the API; detection and `series_keys`/`payment_key` in `src/sonar/recurring/detect.py`; migrations; repairing rows in `data/sonar.db`; templates and UI.

Constraints: AGENTS.md rules: strict TDD, pure functions, integer cents, `tests/test_architecture.py` import rules, ruff clean. Fixtures anonymized: no real names, IBANs, creditor or mandate ids. Decisions D1-D7 below.

Definition of done: a test where a mandate-matched debt's mandate also carries unrelated purchases, two debits share one booking date, and an active recurring payment carries the bare base key shows that payment in the debt's `linked_payments`; a test shows `POST /api/recurring/{id}/dismiss` dismisses a payment and returns it as JSON with `status: dismissed`, and an unknown id answers 404; every existing test passes; the plan `verify` passes.

## Decisions

- D1 `linked_keys` returns, for each matching debit, both its split key from `series_keys` and its base `payment_key`; on an unsplit group the two are equal, so existing results are unchanged | confirmed
- D2 The purpose rule (SPEC §13 "Debt purpose match", `SPEC.md:252`) applies to base keys too: a base key that also holds a debit the purpose rule does not match is never linked, so a shared mandate stays in the forecast | confirmed
- D3 `draft_prefill` reads the debits whose split key or base key equals the payment's `detection_key`; a split key never equals a base key, so split-key prefills are unchanged and a bare-key payment on a split group still gets a draft | confirmed
- D4 SPEC: append one sentence to the bullet at `SPEC.md:253`; no template change, so no visual gate and no CSS rebuild | confirmed
- D5 `POST /api/recurring/{id}/dismiss` calls the recurring store `dismiss` (`src/sonar/recurring/store.py:155`) exactly as the page route `src/sonar/web/pages/recurring.py:147` does, takes no body, answers 200 with the payment as `_recurring_item` (`src/sonar/web/api.py:192`) like `PUT /api/recurring/{id}`, and 404 `{"error": "No such recurring payment: <id>"}` on `PaymentNotFound`; dismissing an already dismissed payment answers 200 unchanged | confirmed
- D6 Docs: one row `| POST | /recurring/{id}/dismiss | - |` after the PUT recurring row at `AGENTS.md:101`; one clause in the SPEC §13 "Recurring descriptions" bullet (`SPEC.md:250`) | confirmed
- D7 N02 depends on N01 only because both write `SPEC.md` (Write paths disjoint within a wave); the changes are otherwise independent | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | debts link the base key of split debits | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N02 | recurring dismiss JSON API | exec | N01 | sonnet/sonnet | 0 | 0 | TODO | |

## N01 debts link the base key of split debits
Do: Make `linked_keys` (`src/sonar/debts/model.py:219`) also return the base `payment_key` of every matching debit, with the purpose exclusion applied to base keys too, and make `draft_prefill` (`src/sonar/debts/drafts.py:44`) also pick debits whose base key equals the payment's key. Append one sentence to the SPEC §13 "Same-day series" bullet saying so.
Context: D1: split key from `series_keys` (`src/sonar/recurring/detect.py:97`) plus base `payment_key` (`:88`) per matching debit; unsplit groups give the same key. D2: for `field == "purpose"`, any key (split or base) that also holds a non-matching debit is dropped, as `src/sonar/debts/model.py:228-231` does now. D3: in `draft_prefill`, a debit counts when its split key or its base key equals `detection_key`; split-key prefills stay unchanged. D4: one sentence appended at `SPEC.md:253`, e.g. "A debt links both the split keys and the unsplit key of its matching debits, and a draft reads debits by either, so a payment kept under the unsplit key stays linked." Callers in `src/sonar/debts/store.py:78,111,162` need no change. No detection, migration or template change.
Read: `src/sonar/debts/model.py:209-235`, `src/sonar/debts/drafts.py:30-80`, `src/sonar/recurring/detect.py:88-120`, `tests/debts/test_model.py:320-420`, `tests/debts/test_drafts.py:1-60,196-245`, `tests/debts/test_store_overview.py:1-150`, `SPEC.md:252-253`
Write: `src/sonar/debts/model.py`, `src/sonar/debts/drafts.py`, `tests/debts/test_model.py`, `tests/debts/test_drafts.py`, `tests/debts/test_store_overview.py`, `SPEC.md`
Test first: in `tests/debts/test_store_overview.py`, a mandate-matched loan whose mandate carries a monthly -10000 debit plus unrelated -2500/-4000 purchases, one purchase on the same date as a monthly debit, and an active recurring payment with the bare base key: `debt_overview` lists that payment in `linked_payments`.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts`
- C2 [review] The test-first case is in `tests/debts/test_store_overview.py`, and `tests/debts/test_model.py` gains: a mandate debt on a split group returns both `#1`, `#2` and the base key; a purpose debt matching only the smaller split series omits the base key (it holds non-matching debits). The two existing split tests (`tests/debts/test_model.py:397,411`) are updated only to the new expected sets.
- C3 [review] A new test in `tests/debts/test_drafts.py` shows `draft_prefill` for a bare-key payment on a split group returns a prefill whose `first_payment_date` is the group's earliest debit; the existing split-key prefill tests are unchanged and pass.
- C4 [review] `linked_keys` and `draft_prefill` stay pure with type hints; `src/sonar/recurring/`, `src/sonar/debts/store.py`, migrations and templates are unchanged; the SPEC diff only appends one sentence to `SPEC.md:253`; fixtures use no real names or ids.
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 recurring dismiss JSON API
Do: Add `POST /api/recurring/{id}/dismiss` to `build_api_router` in `src/sonar/web/api.py`, beside `put_recurring` (`:515`), reusing the recurring store `dismiss`. Document it in the AGENTS.md Categorization endpoints table and the SPEC §13 "Recurring descriptions" bullet.
Context: D5: call `dismiss` (`src/sonar/recurring/store.py:155`) as the page route `src/sonar/web/pages/recurring.py:147` does; no request body; 200 with `_recurring_item(get_payment(conn, id))` (`src/sonar/web/api.py:192`), the same shape as `PUT /api/recurring/{id}`; `PaymentNotFound` gives 404 `{"error": "No such recurring payment: <id>"}` as `src/sonar/web/api.py:525` does; an already dismissed payment answers 200 unchanged. The route sits on the existing `/api` router, so the bearer-token guard (SPEC §13 "API token", `SPEC.md:246`) covers it with no new code. D6: add `| POST | `/recurring/{id}/dismiss` | - |` right after `AGENTS.md:101`; append a clause to `SPEC.md:250`, e.g. "`POST /api/recurring/{id}/dismiss` dismisses a payment as the Fixed payments page does and returns it in the same shape (an unknown id a 404)". No other endpoint, store, template or migration change.
Read: `src/sonar/web/api.py:180-230,322-330,505-540`, `src/sonar/web/pages/recurring.py:145-155`, `src/sonar/recurring/store.py:20-60,150-160`, `tests/web/test_api_recurring.py`, `AGENTS.md:90-105`, `SPEC.md:246,250`
Write: `src/sonar/web/api.py`, `tests/web/test_api_recurring.py`, `AGENTS.md`, `SPEC.md`
Test first: in `tests/web/test_api_recurring.py`, `POST /api/recurring/{id}/dismiss` on an active payment answers 200 with that payment's JSON and `status == "dismissed"`, and `GET /api/recurring` then lists it as dismissed.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_recurring.py`
- C2 [review] New tests in `tests/web/test_api_recurring.py` cover: the test-first case; an unknown id answers 404 with the error JSON; with sign-in on, the right bearer reaches the dismiss route and a wrong one gets 401, following the existing test at `tests/web/test_api_recurring.py:185`.
- C3 [review] The route calls the store `dismiss` and `_recurring_item`, with no new store function and no duplicated SQL; `src/sonar/web/pages/`, `src/sonar/recurring/`, templates and migrations are unchanged.
- C4 [review] `AGENTS.md` gains exactly the one endpoints-table row; the N02 part of the `SPEC.md` diff only appends one clause to the "Recurring descriptions" bullet.
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-06
exec: DONE · 1130 passed
- linked_keys returns split and base keys per matching debit (purpose exclusion on both); draft_prefill reads debits by split or base key; SPEC §13 sentence appended
- tests added in test_store_overview, test_model, test_drafts
check: PASS 2/2
verify: PASS
