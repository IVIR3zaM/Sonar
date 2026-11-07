# Synced debits keep their series
status: DONE
created: 2026-11-07 · updated: 2026-11-07
goal: a direct debit read by the bank sync joins the recurring series its CSV history built by mandate, so each real contract stays one series
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: Recurring detection keeps one series per real contract when the account's history switches from CSV exports
(debits carry a mandate reference and creditor id) to Enable Banking sync (debits carry only the counterparty IBAN).
A synced debit picks up the mandate key of the CSV series paid to the same IBAN, so that series keeps advancing its
last paid date and amount instead of being judged stopped and replaced by a new `counterparty:` series.

In scope: the grouping keys in `src/sonar/recurring/detect.py` (`series_keys`, detect.py:108-128) gain an IBAN
inheritance step for rows without mandate or creditor id; pure tests for the keying and detection, a
`sync_detected` test over stored rows, and one SPEC §13 bullet.

Out of scope: debt match rules, category rules, the bank-sync mapping (`src/sonar/banking/mapping.py`), the UI,
the owner's database and any migration of series already stored under `counterparty:` keys.

Constraints: AGENTS.md rules: strict TDD, pure functions over the existing dataclasses, `today` stays a parameter,
anonymized fixtures (invented IBANs, mandates and creditor ids), KISS, ruff clean; work stays on branch
`worktree-sync-recurring-keys`; confirmed Decisions below.

Definition of done: tests show a mandate-keyed CSV history followed by synced rows without mandates yields one
series per contract whose last paid date and amount advance, with no extra `counterparty:` series; card rows and
rows without an IBAN keep today's keys; a second `sync_detected` after the synced rows arrive updates the stored
series in place, neither deleting nor duplicating it; with several contracts on one IBAN, a reference token in the synced purpose (customer or contract number) picks its own contract even when the amount or day points to another; verify passes.

## Decisions

- D1 Synced debits carry the counterparty IBAN but no mandate_ref and no creditor_id (`src/sonar/banking/mapping.py:64`); CSV debits from `deutsche_bank_giro` carry IBAN, mandate and creditor id. | confirmed
- D2 Which rows inherit: only a row whose own `payment_key` would be `counterparty:` (not a card settlement, no mandate_ref, no creditor_id) and that has an IBAN; card rows and creditor-only rows keep today's key. | confirmed
- D3 Choosing the group: candidates are the mandate base keys (before any `#rank` split) among the same input rows that have a row with the same IBAN (compared without spaces, case-insensitive). One candidate: join it whatever the amount. Several: rank first by the count of reference tokens shared between the row's purpose and the purposes of all that candidate's mandate rows, higher wins (a token is a maximal alphanumeric run of the `normalize_text`ed purpose, at least 4 characters, containing a digit; counted as distinct tokens), then candidates whose amounts on their latest booking date include the row's absolute amount, then the smallest day-of-month distance between the row and that latest booking day, wrapping at the month end (31-day cycle, as `_is_salary` detect.py:67-70), then the lowest key. None: key unchanged. Candidates come from mandate rows only, never from rows that inherited. | confirmed
- D4 Inheritance lives in `series_keys` (detect.py:108), so the same-day split ranks inherited rows with their group and the debt helpers that call it (`linked_keys` debts/model.py:261, `draft_prefill` debts/drafts.py:43) see the keys detection stores; `payment_key` stays per-row and unchanged. | confirmed
- D5 The stopped-series check (detect.py:171) needs no code change: once synced rows share the mandate key the group's last payment is recent; a test pins this. | confirmed
- D6 Unedited series the owner's DB already holds under `counterparty:` keys from earlier syncs are deleted by the next `sync_detected` (store.py:257-261); edited ones stay; no migration. | confirmed
- D7 SPEC.md gets one §13 bullet after line 280 stating the inheritance rule of D2 and D3. | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | iban inherits mandate key | exec | - | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N02 | purpose tokens pick the mandate | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |

## N01 iban inherits mandate key
Do: In `src/sonar/recurring/detect.py`, make `series_keys` (detect.py:108-128) replace the base key of each row
  whose `payment_key` starts with `counterparty:` and that has an `iban` by the mandate base key chosen per D3, before
  the same-day ranking, in a small pure helper. `payment_key` (detect.py:96-105) and the stopped check
  (detect.py:171) stay unchanged. Append the SPEC §13 bullet "Synced debits keep their series (§6 Detection)" after
  SPEC.md:280 stating D2 and D3.
Context: D1 synced rows have only `iban` (`src/sonar/transactions.py:25`). D2 only `counterparty:` rows with an
  IBAN inherit. D3 one candidate: join even if the amount changed; several: equal latest amount, then nearest day
  with month-end wrap, then lowest key; none: unchanged; candidates from mandate rows only; IBAN compared without
  spaces, case-insensitive. D4 change lives in `series_keys`, so debts (debts/model.py:261, debts/drafts.py:43) see
  it; their existing tests must still pass. D5 no change at detect.py:171. Fixtures invented (e.g.
  `DE00 1111 ...` IBANs, `MANDATE-A` refs), never real names.
Read: `src/sonar/recurring/detect.py`, `src/sonar/recurring/store.py`, `tests/recurring/test_detect.py`, `tests/recurring/test_store_sync.py`, `src/sonar/transactions.py`
Write: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect_synced.py`, `tests/recurring/test_store_sync_synced.py`, `SPEC.md`
Test first: `tests/recurring/test_detect_synced.py`: (a) three monthly mandate rows at 19.99 to IBAN X, then two
  synced rows (iban X, no mandate) at 21.99: `detect_recurring` returns one payment keyed `mandate:<cred>/<ref>`,
  last_paid_date the last synced date, amount 2199, no `counterparty:` key; (b) one IBAN, mandates A (3.00 and 30.00
  on day 14), B (12.75 day 1), C (39.00 day 2), D (41.00 day 7): synced rows of each amount on those days join their
  own keys (A splits into `#1`/`#2`); a synced 13.50 on day 2 joins C and on day 31 joins B; (c) a card row with
  IBAN X keeps `card:`, a row without IBAN and a row whose IBAN no mandate group has keep `counterparty:`, a
  creditor-only row keeps `creditor:`. `tests/recurring/test_store_sync_synced.py`: SQL-seeded mandate rows,
  `sync_detected`, then synced rows, `sync_detected` again: same row id, one row, last_paid_date and amount advanced.
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring tests/debts`
- C2 [review] the inheritance is one pure helper used by `series_keys`; `payment_key` and detect.py:171 are
  unchanged; candidates come only from mandate rows; tests cover cases (a), (b) and (c) and the two-sync store test
  with anonymized fixtures; the SPEC §13 bullet is appended after line 280.
- C3 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 purpose tokens pick the mandate
Do: In `src/sonar/recurring/detect.py`, `_inherit_mandate_keys` (detect.py:131-160) ranks several mandate
  candidates of one IBAN first by shared reference tokens (amended D3), before its existing equal-amount,
  nearest-day and lowest-key order (detect.py:149-159). Collect each candidate's tokens over all its mandate rows,
  not only the latest date; extract tokens in one small pure helper. Rewrite the D3 part of the SPEC §13 bullet
  "Synced debits keep their series" (SPEC.md:282) to state the new order.
Context: D3 (amended): candidates are the mandate base keys whose rows share the row's IBAN; one candidate: join
  it; several: highest count of distinct shared tokens, then latest-date amount equal to the row's, then nearest
  day of month with month-end wrap (31-day cycle), then lowest key; none: unchanged; candidates from mandate rows
  only. A token is a maximal alphanumeric run of `normalize_text(purpose)` (`src/sonar/importing/dedup.py:50`), at
  least 4 characters, containing a digit (so `PP.1998.PP` gives `1998`, `Kd-Nr 6108667418` gives `6108667418`;
  `pp`, `abschlag` give none). D2 and the single-candidate rule are unchanged. Fixtures invented, never real
  names, numbers or IBANs.
Read: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect_synced.py`, `tests/recurring/test_store_sync_synced.py`, `src/sonar/importing/dedup.py`
Write: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect_synced.py`, `SPEC.md`
Test first: in `tests/recurring/test_detect_synced.py`, over `series_keys` and `detect_recurring` with one
  IBAN per case: (a) two contracts, gas mandate rows with purpose token `400100111111` at 150.00 and power mandate
  rows token `400100222222` at 152.00: a synced 152.00 whose purpose carries `400100111111` joins gas; (b) price
  change, two mandates with customer numbers `7001000001` (61.94) and `7001000002` (64.61), same day: a synced
  64.61 carrying `Kd-Nr 7001000001` joins the first; (c) mandates whose purposes read `PP.1111.PP` and `PP.2222.PP`
  at equal amounts on the nearer day of the second: a synced row with `PP.1111.PP` joins the first; (d) synced rows
  with no shared token keep the amount, day, key order (the existing tests still pass).
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring tests/debts`
- C2 [review] token ranking precedes amount, day and key in `_inherit_mandate_keys`; tokens come from one pure
  helper applying the 4-character, contains-a-digit rule to `normalize_text`ed purposes, over all of a candidate's
  mandate rows; a lone candidate is still joined regardless of tokens; tests (a)-(d) use invented fixtures; the
  SPEC.md:282 bullet states the new order.
- C3 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-11-07
exec: DONE · 2247 passed, 4 skipped; recurring/debts 274 passed; ruff check and format clean
- Added pure mandate-key inheritance before same-day ranking and SPEC §13 amendment.
- Anonymized detection and two-sync persistence tests cover amount changes, shared IBAN selection, exclusions, latest amounts and key ties.
check: PASS 2/2
verify: PASS

### N02 try 1 · 2026-11-07
plan: BRIEFED
- owner amended D3: shared purpose reference tokens rank mandate candidates before amount, day and key
- new node after N01: token helper, three anonymized shapes (two contracts one IBAN, price change, distinguishing token), SPEC.md:282 bullet updated
exec: DONE · 2257 passed, 4 skipped; 284 recurring/debt tests passed; ruff check and format clean
- detect.py: shared distinct reference tokens across all mandate rows rank before latest amount, wrapped day and key; SPEC.md D3 updated.
- test_detect_synced.py: failing-first coverage for contract references, price changes, punctuation, normalization, distinct counts and older rows; existing fallback tests retained.
check: PASS 2/2
verify: PASS
