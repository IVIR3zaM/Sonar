# Debt purpose match
status: DONE
created: 2026-10-06 · updated: 2026-10-06
goal: A debt can be matched to its bank payments by text in the payment purpose, so one installment plan on a shared creditor mandate counts only its own debits.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: some creditors run many plans and subscriptions through one SEPA mandate and one counterparty, and only an order number in the purpose tells an installment plan apart. A debt gets a third match field, `purpose`, so its paid-so-far, remaining and end figures count only the debits whose purpose contains that text, and it never hides the shared recurring payment from the forecast.

In scope: the `purpose` match field in the pure debts model (`MATCH_FIELDS`, `matches`, `linked_keys`); a migration that rebuilds the `debts` table so its CHECK accepts `purpose` while keeping every row and id; the "Purpose contains" option in the Debts page's match-field select (add forms and draft-completion forms); tests proving `POST /api/debts` accepts it and `GET /api/debts` returns it; one SPEC §13 amendment and the AGENTS.md `/debts` row.

Out of scope: editing a debt; any other page or UI; changing how counterparty and mandate rules match or link; the recurring detection key.

Constraints: AGENTS.md rules: strict TDD, functional core (the matching and linking rules are pure in `debts/model.py`), `store.py` the only DB access, a new migration file (never edit an applied one), hand-entered debts survive the upgrade, `tests/test_architecture.py`, page tests on stable hooks, ruff clean. Decisions D1-D10 below.

Definition of done: the plan `verify` passes; a smoke run on a temp DB shows an installment with `match_field: purpose` counting only the debits whose purpose contains its text; after the last node's commit the orchestrator pushes `main` once so CI deploys (D10).

## Decisions

- D1 Purpose matching: `matches` with field `purpose` is true for a debit (amount < 0) when `normalize_text(rule.value) in normalize_text(tx.purpose)`, the same case- and space-insensitive substring test counterparty uses; credits never match | confirmed
- D2 Link guard scope: the "link only when every debit of that payment's key matches the rule" guard applies to `purpose` rules only; counterparty and mandate linking stay exactly as today | confirmed
- D3 Where the guard lives: inside `linked_keys` (`src/sonar/debts/model.py:217`), so the forecast link (`debt_overview`), draft suppression (`sync_drafts`) and API draft closing (`add_debt_closing_drafts`) all agree: a purpose debt on a shared mandate neither hides, suppresses nor closes that shared payment | confirmed
- D4 "Every debit of the key": every debit in the whole transaction history whose `payment_key` equals that key, regardless of date; credits on the key are ignored | confirmed
- D5 Migration: new `src/sonar/migrations/0011_debts_purpose_match.sql` creates `debts_new` with the columns, order and CHECKs of `0004_debts.sql:9`, except `match_field IN ('counterparty', 'mandate', 'purpose')`; copies every row with an explicit column list including `id`; drops `debts`; renames `debts_new` to `debts`. No table references `debts`, so no foreign-key handling is needed | confirmed
- D6 UI: the shared `match_options` (`src/sonar/web/templates/debts.html:10`) gains `("purpose", "Purpose contains")` after Mandate, which covers both add forms and both draft-completion forms; the match-value help text becomes "Counterparty text, SEPA mandate reference or purpose text" | confirmed
- D7 CSS: the template change adds no new class, so `sonar.css` is not rebuilt or committed | confirmed
- D8 Docs: one SPEC §13 bullet "Debt purpose match (§7)" after `SPEC.md:251`, and the AGENTS.md POST `/debts` row (`AGENTS.md:103`) notes that `match_field` is `counterparty`, `mandate` or `purpose` | confirmed
- D9 Visual gate: none; the owner skipped it, and the template change is one select option and one help text | confirmed
- D10 Push: the header says `push: none`. After the N02 commit the orchestrator runs `git push origin main` once, which the owner pre-authorized | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | purpose match in model and schema | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N02 | purpose option on page, API and docs | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |

## N01 purpose match in model and schema
Do: Add `purpose` as a debt match field in the pure model, guard its linking so a shared payment key is never linked, and add a migration that lets the `debts` table store it while keeping every existing row and id.
Context: D1: `MATCH_FIELDS` (`src/sonar/debts/model.py:21`) gains `"purpose"`; in `matches` (`:36`) a purpose rule is a debit whose `normalize_text(tx.purpose)` contains `normalize_text(rule.value)`. Order-number text like "305-7936467-3301953" must match regardless of case and spacing.
  D2/D3/D4: in `linked_keys` (`:217`), for a purpose rule only, drop a key when any debit in `txs` with that `payment_key` (`src/sonar/recurring/detect.py:85`) does not match the rule; credits are ignored. Counterparty and mandate behave as now. Explain the why in one comment (a shared creditor mandate groups other subscriptions under the same key).
  `installment_status`, `loan_status` and `last_payment_date` need no change: they already filter by `matches`.
  D5: new `src/sonar/migrations/0011_debts_purpose_match.sql`: header comment citing SPEC §13 Debt purpose match; `CREATE TABLE debts_new` copying `0004_debts.sql:9-40` with `match_field IN ('counterparty', 'mandate', 'purpose')`; `INSERT INTO debts_new (<every column>) SELECT <every column> FROM debts`; `DROP TABLE debts`; `ALTER TABLE debts_new RENAME TO debts`. Never edit `0004_debts.sql`.
  Store: `_debt_from_row` (`src/sonar/debts/store.py:230`) already builds `MatchRule` from the row, so a stored purpose debt loads with no store change.
Read: `src/sonar/debts/model.py`, `src/sonar/migrations/0004_debts.sql`, `tests/debts/test_model.py`, `tests/migrations/test_0008.py`, `tests/debts/test_store_overview.py`
Write: `src/sonar/debts/model.py`, `src/sonar/migrations/0011_debts_purpose_match.sql`, `tests/debts/test_model.py`, `tests/migrations/test_0011.py`, `tests/debts/test_store_overview.py`
Test first: in `tests/debts/test_model.py`, a purpose rule "305-7936467-3301953" matches a debit whose purpose holds "AMZN Ratenzahlung 305-7936467-3301953" and not a debit on the same mandate whose purpose holds another order number.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts tests/migrations`
- C2 [review] `tests/debts/test_model.py` covers: purpose match is case- and space-insensitive; a credit with the text never matches; `MatchRule("purpose", " ")` is rejected; `linked_keys` of a purpose rule omits a key that also holds a non-matching debit and keeps a key whose debits all match; counterparty and mandate `linked_keys` tests are unchanged and pass.
- C3 [review] `tests/migrations/test_0011.py` applies migrations before 0011 (the copy-dir pattern of `tests/migrations/test_0008.py:20`), inserts an installment and a loan with chosen non-sequential ids, applies all migrations, and asserts every row and id is unchanged; afterwards a `purpose` row inserts, `match_field = 'iban'` and a loan missing `balance_as_of` still raise `IntegrityError`, and `PRAGMA table_info(debts)` lists the same columns in the same order as before.
- C4 [review] `tests/debts/test_store_overview.py` has one test: two debits share a mandate with different purposes, a recurring payment is stored for that key, and a purpose debt matching one of them counts only that debit in `paid_cents` and has empty `linked_payments`.
- C5 [review] `git diff` shows no change to `src/sonar/migrations/0004_debts.sql` and no change to how counterparty or mandate rules match or link.
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 purpose option on page, API and docs
Do: Offer "Purpose contains" in the Debts page's match-field select, prove the page and `POST /api/debts` save a purpose debt and `GET /api/debts` returns it, and document the field in SPEC §13 and AGENTS.md.
Context: D6: `match_options` (`src/sonar/web/templates/debts.html:10`) gains `("purpose", "Purpose contains")` after `("mandate", "Mandate")`; it feeds the add forms (`:167`, `:223`) and the draft-completion forms (`:71`). The match-value help text at `:72`, `:168`, `:224` becomes "Counterparty text, SEPA mandate reference or purpose text". `src/sonar/web/pages/debts.py` and `src/sonar/web/api.py` need no change: `MatchRule` (`src/sonar/debts/model.py:25`, N01) validates the field.
  D7: no new CSS class, so do not rebuild or commit `sonar.css`.
  D8: in SPEC.md, after `SPEC.md:251`, add one bullet "Debt purpose match (§7)": a debt's match rule may be `purpose`, a case- and space-insensitive substring of a debit's purpose; a purpose debt links a recurring payment only when every debit of that payment's key matches it, so a shared mandate stays in the forecast; the Debts page offers "Purpose contains" and `/api/debts` accepts and returns `purpose`. In AGENTS.md, the POST `/debts` row (`AGENTS.md:103`) body becomes "`kind` plus the installment or loan fields above; `match_field` is `counterparty`, `mandate` or `purpose`". No real names, order numbers or mandate ids in either file.
Read: `src/sonar/web/templates/debts.html`, `tests/web/test_debts_page.py`, `tests/web/test_debts_drafts_page.py`, `tests/web/test_api_debts.py`, `tests/html.py`
Write: `src/sonar/web/templates/debts.html`, `tests/web/test_debts_page.py`, `tests/web/test_debts_drafts_page.py`, `tests/web/test_api_debts.py`, `SPEC.md`, `AGENTS.md`
Test first: in `tests/web/test_debts_page.py`, the installment add form's `select[name=match_field]` has an option with value `purpose`.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_debts_page.py tests/web/test_debts_drafts_page.py tests/web/test_api_debts.py`
- C2 [review] Tests cover: both add forms and a draft-completion form offer `purpose`; posting the installment add form with `match_field=purpose` stores a debt whose `match.field` is `purpose`; `POST /api/debts` with `match_field: "purpose"` answers 201 and `GET /api/debts` returns `match_field: "purpose"` with `paid_cents` counting only the debits whose purpose holds the text; `match_field: "iban"` still answers 400 with `field: match_field`.
- C3 [smoke] Start the app on a temp DB under `$TMPDIR` (never `data/sonar.db`), seed two debits on one mandate with different purpose order numbers (sqlite3 insert or a fixture import), `POST /api/debts` an installment with `match_field: "purpose"` and one order number; `GET /api/debts` shows `paid_cents` equal to that one debit and an empty `linked_payment_ids`. Stop the app.
- C4 [review] `git diff SPEC.md AGENTS.md` adds exactly one §13 bullet and changes only the POST `/debts` row; `sonar.css` is unchanged.
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-06
exec: DONE · 1109 passed
- purpose match field in model.py, linked_keys drops keys shared with non-matching debits for purpose rules
- migration 0011 rebuilds debts with purpose allowed, ids and rows kept; tests added in test_model, test_0011, test_store_overview
check: PASS 2/2
verify: PASS

### N02 try 1 · 2026-10-06
exec: DONE · 1114 passed
- Purpose contains option and help text in debts.html; page, drafts and API tests
- SPEC §13 bullet and AGENTS.md POST /debts row; smoke covered by API test (TestClient, temp DB)
check: PASS 2/2
verify: PASS
