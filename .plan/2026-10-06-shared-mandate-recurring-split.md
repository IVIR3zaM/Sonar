# Shared mandate recurring split
status: DONE
created: 2026-10-06 · updated: 2026-10-06
goal: Recurring detection finds each series when one payment key carries several payments on the same booking date, and every consumer of the key agrees on the split keys.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: some creditors collect two separate charges under one mandate on the same day, for example two quarterly property charges of different size. Detection groups them under one key, sees a zero-day gap and finds nothing. Such a group is split into one series per amount rank on each date, so each charge is detected on its own with its own amount and its own next due date.

In scope: a pure splitting rule in `src/sonar/recurring/detect.py` used by recurring and income detection; the debts consumers that rebuild keys from transactions (`linked_keys` in `src/sonar/debts/model.py`, `draft_prefill` in `src/sonar/debts/drafts.py`) use the same split keys; tests in `tests/recurring/` and `tests/debts/`; one SPEC §13 amendment.

Out of scope: templates and UI; migrations; how debt match rules (counterparty, mandate, purpose) match a transaction; editing rows in `data/sonar.db`; any other key scheme change.

Constraints: AGENTS.md rules: strict TDD, pure functions over plain dataclasses, `store.py` the only DB access, `tests/test_architecture.py` import rules, ruff clean. Fixtures are anonymized: no real names, IBANs, creditor or mandate ids. Decisions D1-D6 below.

Definition of done: a test with two same-day quarterly payments under one mandate detects two quarterly payments keyed `<base>#1` and `<base>#2` with the right amounts; every existing detection test passes unchanged; debt drafts and links resolve the split keys; the plan `verify` passes.

## Decisions

- D1 Split rule: after detection's filter, a `payment_key` group that holds two or more payments on any one booking date is split: every payment in it gets the key `<base key>#<rank>`, where rank is its 1-based position on its own date ordered by absolute amount, largest first, ties in input order. A date with one payment gives rank 1. A group with at most one payment per date keeps its base key unchanged | confirmed
- D2 Key change on split: when a group gains its first same-day pair, all its keys change. `sync_detected` (`src/sonar/recurring/store.py:187`) then deletes an untouched base-key row and inserts `#1`/`#2`; an edited, described or dismissed base-key row stays as an orphan the owner can delete. No migration or data repair | confirmed
- D3 One pure helper in `detect.py`, `series_keys(txs) -> list[tuple[ParsedTransaction, str]]` (each transaction with its split-aware key, input order kept); `_detect_series` and both debts consumers use it; `payment_key` stays the base key | confirmed
- D4 Debts consumers compute split keys over every debit (amount < 0) in the whole history, without the category filter detection applies; they differ from detection only when a same-day sibling under one key sits in an excluded category, which is accepted. `_match_rule` (`src/sonar/debts/drafts.py:68`) still prefills a mandate rule for a `mandate:…#n` key; match rules are not changed | confirmed
- D5 SPEC: one §13 bullet "Same-day series (§6)" appended after the last bullet of §13 (`SPEC.md:252`) | confirmed
- D6 No template change, so no visual gate and no CSS rebuild; push stays `none` | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | split same-day series in detection | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N02 | debts use split series keys | exec | N01 | sonnet/sonnet | 1 | 1 | DONE | |

## N01 split same-day series in detection
Do: Add the pure helper `series_keys` to `src/sonar/recurring/detect.py` and group by its keys in `_detect_series` (`:70`), so same-day payments under one key become separate series. Document the rule in SPEC §13.
Context: D1: a group (by `payment_key`, `:85`) with two or more payments on any booking date splits: each payment's key is `<base>#<rank>`, rank 1-based on its own date by absolute amount, largest first, ties in input order; a date with one payment gives rank 1. A group with at most one payment per date keeps the bare base key, so existing `recurring_payments` rows and owner edits survive.
  D3: `series_keys(txs: Iterable[ParsedTransaction]) -> list[tuple[ParsedTransaction, str]]` keeps input order; `payment_key` stays public and unchanged (debts import it). `_detect_series` applies `keep` first, then keys the kept rows with `series_keys`, so `detect_recurring` and `detect_income` both split. Update the module docstring's key sentence; one comment says why (one mandate can carry several charges on one day).
  D5: append to SPEC §13 after `SPEC.md:252` one bullet "Same-day series (§6)": when one grouping key holds more than one payment on a booking date, the group splits into series by amount rank within each date, largest first, keyed `<key>#1`, `#2`, …; groups with one payment per date keep their key. No real names or ids.
Read: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect.py`, `SPEC.md:82-92`, `SPEC.md:225-252`
Write: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect.py`, `SPEC.md`
Test first: in `tests/recurring/test_detect.py`, three quarterly dates each with two debits under one mandate (creditor `CREDITOR`, mandate `M-0001`, amounts -1205 then -7612 in that input order) detect two payments keyed `mandate:<CREDITOR>/M-0001#1` (amount 7612, interval 3) and `…#2` (amount 1205, interval 3).
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring`
- C2 [review] New tests cover: the two-series case above; a quarter where only the larger charge was paid still lets `#1` detect and its lone payment ranks 1; `series_keys` keeps the bare `payment_key` for a group with one payment per date; a same-day pair of income credits also splits via `detect_income`. Every test that existed before is unchanged.
- C3 [review] `series_keys` is a pure function with type hints, `_detect_series` groups by its keys, `payment_key` (`detect.py:85`) is unchanged, and the SPEC diff is exactly one §13 bullet with no real names or ids.
- C4 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## N02 debts use split series keys
Do: Make the debts functions that rebuild detection keys from transactions use `series_keys` (N01) instead of `payment_key`, so debt links, draft suppression and draft prefill agree with the split keys detection stores. Move the second debit of `test_linked_keys_purpose_omits_a_key_shared_with_a_non_matching_debit` (`tests/debts/test_model.py:351`) to another booking date, so it still tests a key shared across dates rather than a same-day split.
Context: D1: a key group with two or more debits on one booking date splits into `<base>#<rank>` keys, rank by absolute amount on that date, largest first, ties in input order.
  D3: `series_keys(txs)` in `src/sonar/recurring/detect.py` returns each transaction with its split-aware key (`<base>#<rank>` when its key group has a same-day pair, else the bare `payment_key`).
  D4: both consumers key every debit (amount < 0) of the whole history with `series_keys`, no category filter. `linked_keys` (`src/sonar/debts/model.py:219`): the matching keys and the purpose guard (`:228-233`) use those keys; with split keys a purpose debt matching only the smaller same-day charge links that series' `#2` key. `draft_prefill` (`src/sonar/debts/drafts.py:44`): its debits are those whose series key equals `payment.detection_key`. `_match_rule` and match rules stay unchanged. `src/sonar/debts/store.py` passes all transactions already and needs no change; drop the `payment_key` import where it becomes unused.
  The test at `tests/debts/test_model.py:351` relies on `_tx`'s default date (`:19`) for both debits; under D1 they become `#1`/`#2`. Only its second debit's `booking_date` changes (e.g. `date(2026, 2, 5)`); its name, purposes, amounts and assertion (`frozenset()`) stay.
Read: `src/sonar/debts/model.py:209-235`, `src/sonar/debts/drafts.py`, `src/sonar/recurring/detect.py`, `tests/debts/test_model.py:17-30,320-415`, `tests/debts/test_drafts.py`
Write: `src/sonar/debts/model.py`, `src/sonar/debts/drafts.py`, `tests/debts/test_model.py`, `tests/debts/test_drafts.py`
Test first: in `tests/debts/test_drafts.py`, a payment with `detection_key` `mandate:CRED/M-1#2` over quarterly same-day debit pairs (larger and smaller) prefills `first_payment_date` from the earliest smaller debit and ignores the larger ones.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts`
- C2 [review] New tests cover: the `#2` draft prefill above; `linked_keys` of a mandate debt on a split group returns both `#1` and `#2` keys; `linked_keys` of a purpose debt whose text is only in the smaller charges' purpose returns exactly the `#2` key.
- C3 [review] `git diff tests/` changes no existing test except the one `booking_date` argument added to the second debit of `test_linked_keys_purpose_omits_a_key_shared_with_a_non_matching_debit`, whose assertion stays `frozenset()`.
- C4 [review] `git diff` shows no change to `matches`, `MatchRule`, `_match_rule` or `src/sonar/debts/store.py`.
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-06
exec: DONE · 1119 passed
- series_keys in detect.py; _detect_series groups by it; SPEC §13 Same-day series bullet; 5 new tests
- ranks computed per (base key, date); only groups with a same-day pair get #rank suffix
check: PASS 2/2
verify: PASS

### N02 try 1 · 2026-10-06
exec: BLOCKED · existing test_linked_keys_purpose_omits_a_key_shared_with_a_non_matching_debit has two same-day equal-amount debits, which series_keys splits into #1/#2, so linked_keys returns {#1} not empty; C2 forbids changing existing tests. Impl and new tests done; fix = give that test's two debits different dates

### N02 replan 1 · 2026-10-06
plan: REPLANNED
- cause: existing test at tests/debts/test_model.py:351 has two same-day debits on one key, which D1 splits into #1/#2; old C2 forbade editing it
- change: Do and new C3 allow only moving that test's second debit to another booking date, assertion unchanged; criteria renumbered C1-C5

### N02 try 1 · 2026-10-06
exec: DONE · 1123 passed
- linked_keys and draft_prefill use series_keys over all debits; payment_key import dropped
- Second debit of purpose-omits test moved to 2026-02-05; added #2 prefill and split linked_keys tests
check: PASS 2/2
verify: PASS
