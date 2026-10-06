# Same-day split by nearest amount
status: DONE
created: 2026-10-06 · updated: 2026-10-06
goal: A key that splits into same-day series puts each payment on a non-collision date into the series of nearest amount, so series with different intervals under one key are each detected.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: the same-day split from the previous plan ranks payments by amount only on the dates that hold several of them, and gives every lone payment rank 1. When a lender's mandate carries a small monthly installment and a large quarterly settlement that meet on one day, every small monthly payment lands in `#1` beside the large ones, so detection reports a wrong monthly series at the large amount and no small series. Lone payments must instead join the series whose typical amount they resemble.

In scope: the pure `series_keys` in `src/sonar/recurring/detect.py`; its tests in `tests/recurring/test_detect.py`; one debts test proving a draft prefill picks up the reassigned lone debits; the wording of the existing SPEC §13 "Same-day series" amendment.

Out of scope: the `<key>#<n>` scheme itself; `payment_key`; migrations; repairing rows already in `data/sonar.db`; templates and UI; debt match rules.

Constraints: AGENTS.md rules: strict TDD, pure functions, integer cents, `tests/test_architecture.py` import rules, ruff clean. Fixtures anonymized: no real names, IBANs, creditor or mandate ids. Decisions D1-D6 below.

Definition of done: a test with a monthly small series and a quarterly large series under one key, meeting on one date, detects a monthly series at the small amount keyed `#2` and a quarterly series at the large amount keyed `#1`; the existing two-quarterly same-day test and every other existing test pass unchanged; the plan `verify` passes.

## Decisions

- D1 Collision rule kept: per base key, k = the most payments on any one booking date; a group with k <= 1 keeps the bare base key; payments on a date holding exactly k payments rank by absolute amount, largest first, ties in input order, keyed `#1`..`#k` | confirmed
- D2 Reference amount of rank r = `statistics.median_low` of the absolute amounts ranked r on the collision dates (integer cents, no float) | confirmed
- D3 A date with m < k payments: sort its payments largest first (ties in input order) and give them the increasing rank combination (`itertools.combinations(range(1, k+1), m)`) with the smallest total absolute-cents distance to the references; the first such combination wins a tie. m = 1 reduces to the nearest reference, the lower rank on a tie | confirmed
- D4 Debts consumers (`linked_keys` in `src/sonar/debts/model.py:219`, `draft_prefill` in `src/sonar/debts/drafts.py:44`) call `series_keys` and follow without code change | confirmed
- D5 Keys of already-stored split rows may change on the next sync; `sync_detected` (`src/sonar/recurring/store.py:187`) replaces untouched rows, edited ones stay as orphans the owner deletes. No migration, no data repair | confirmed
- D6 SPEC: rewrite the existing bullet at `SPEC.md:253` in place (no new bullet) to state D1-D3; no template change, so no visual gate and no CSS rebuild | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | assign lone payments by nearest amount | exec | - | sonnet/sonnet | 1 | 0 | DONE | |

## N01 assign lone payments by nearest amount
Do: Change `series_keys` (`src/sonar/recurring/detect.py:96`) so a payment on a date with fewer than k payments joins the series of nearest reference amount instead of rank 1, and rewrite the SPEC §13 "Same-day series" bullet to match.
Context: D1: per base key (`payment_key`, `:87`), k = most payments on one date; k <= 1 keeps the bare key; on dates with exactly k payments rank by absolute amount, largest first, ties in input order, keyed `<base>#1`..`#k`.
  D2: reference of rank r = `median_low` (already imported, `:17`) of the absolute amounts ranked r on those collision dates.
  D3: on a date with m < k payments, sort them largest first (ties in input order) and assign the increasing rank combination from `itertools.combinations(range(1, k + 1), m)` with the least total absolute distance to the references; the first combination wins ties. So two payments on one date never share a series.
  D4: `linked_keys` and `draft_prefill` already call `series_keys`; no debts code changes. Keep small, named helpers and input order of the result; update the `series_keys` comment to say why (lone payments belong to the series they resemble).
  D6: replace the bullet at `SPEC.md:253` in place: collision dates (most payments on one date) rank by amount `#1`..`#k`, largest first; a payment on any other date joins the series whose median collision amount is nearest, never two on one date in one series; groups with one payment per date keep their key. No real names or ids.
Read: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect.py:349-410`, `tests/debts/test_drafts.py:195-240`, `SPEC.md:253`
Write: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect.py`, `tests/debts/test_drafts.py`, `SPEC.md`
Test first: in `tests/recurring/test_detect.py`, one mandate (`CREDITOR`, `M-0001`) with a monthly -3300 debit on the 1st of 2026-01 to 2026-09 and quarterly debits -67000 on 2026-03-03, -170000 on 2026-06-02, -120000 on 2026-09-01 (only 2026-09-01 collides) detects `MANDATE_KEY#2` monthly at 3300 and `MANDATE_KEY#1` quarterly at 120000, and nothing else.
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring tests/debts`
- C2 [review] New tests cover: the monthly/quarterly case above; a `series_keys` unit test where k = 3 (one date with -9000, -5000, -1000) and another date with -5100, -950 gives that date `#2`, `#3`; a lone payment equidistant from two references gets the lower rank. Every test that existed before is unchanged.
- C3 [review] A new test in `tests/debts/test_drafts.py` shows `draft_prefill` for `MANDATE_KEY#2` on the monthly/quarterly shape starts at the first small lone debit, not the collision date.
- C4 [review] `series_keys` stays pure with type hints, uses integer cents only, `payment_key` is unchanged, no debts source file changed, and the SPEC diff only rewrites the line at `SPEC.md:253`, without real names or ids.
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-06
exec: DONE · 1127 passed
- series_keys ranks collision dates by amount, lone/short dates take nearest-reference rank combination (helpers _rank_group, _reference_amounts, _nearest_ranks); SPEC §13 bullet rewritten
- tests added in test_detect.py and test_drafts.py; ties go to the first (lowest) combination via min()
check: PASS 2/2
verify: PASS
