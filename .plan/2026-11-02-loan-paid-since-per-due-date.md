# Loan paid since per due date
status: DONE
created: 2026-11-02 · updated: 2026-11-02
goal: a loan's "Paid since statement" counts at most its scheduled payment per due date, so a shared mandate no longer overcounts
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: A loan's "Paid since statement" figure reflects only that loan's own scheduled payments. Today it adds up every matching debit after the statement date. So when several loans share one mandate, each loan counts the whole combined monthly debit, and a loan on a mandate shared with unrelated purchases counts those purchases too. After this change, each scheduled payment that is already due is matched to at most one fitting debit near its due date, and it counts at the scheduled amount.

In scope: the paid-since computation in `loan_status` (`src/sonar/debts/model.py:135-153`), driven by the amortization schedule it already builds (`amortization.loan_schedule`, `src/sonar/debts/amortization.py:31-47`) and the shared tolerance `recurring.schedule.TOLERANCE` (`src/sonar/recurring/schedule.py:15`, 7 days). It also covers new pure-function tests with anonymized fixtures, a SPEC §13 amendment bullet stating the rule, and updating the single API test that asserted the old sum rule (`tests/web/test_api_debts.py:245`).

Out of scope: installments (`installment_status` is unchanged), extra repayments (Sondertilgung) counting toward paid since (they deliberately do not count), projected balance, payoff date, the forecast schedule, templates and CSS, and any change to production data.

Constraints: AGENTS.md engineering rules. Strict TDD: the failing tests come first. The logic is a pure function with `today` as a parameter. Money is integer cents. KISS: no new module and no new abstraction beyond a small private helper. Ruff check and format are clean. The confirmed Decisions below apply.

Definition of done: verify passes. Three linear loans on one mandate, each paid by one combined monthly debit, each show only their own scheduled payments as paid since statement. Unrelated smaller or off-window debits on the mandate add nothing. An ordinary loan, with one debit per month at the rate on its due day, shows the same figure as before.

## Decisions

- D1 Rule: for each payment in the loan's schedule with `due_date <= today`, the candidates are the matching debits (`matches`, model.py:36) with `abs(booking_date - due_date) <= TOLERANCE`, both ends inclusive, and `abs(amount_cents) >=` that payment's `amount_cents`. Pick the closest one to the due date. A debit counts for at most one due date, and it adds the scheduled `amount_cents`, not the debit amount. Paid since is the sum of these. | confirmed
- D2 Consequences we accept, all following from the request: a debit that is below the scheduled amount (even by a cent) or more than 7 days from a due date no longer counts. An early debit whose due date is still after `today` counts only once that due date passes. On a shared mandate, a larger unrelated debit that falls in a due window can still count. | confirmed
- D3 Tie-break: due dates are processed in ascending order. Among equally close candidates the earlier booking date wins. This only makes the result deterministic, because the counted value is always the scheduled amount. | confirmed
- D4 `tests/web/test_api_debts.py:230-246` asserts `loan["paid_cents"] == 10_000` from an M-2 debit on 2026-08-10, which is 20 days from any due date and below the 20_000 rate. Under the new rule it counts 0. Fix: in that test only, post the loan with `rate_cents: 10_000` and insert an M-2 debit on 2026-07-30 with `_insert_tx` (fixed -10000), so the assertion stays 10_000 and stays meaningful. | confirmed
- D5 SPEC: add one new bullet at the end of §13: "Loan paid since statement (§7; overrides "Paid so far is counted from those transactions" for loans): ...", stating D1 in plain words and that extra repayments do not count. | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | paid since per due date | exec | - | codex@medium/sonnet | 1 | 0 | DONE | |

## N01 paid since per due date
Do: In `loan_status` (src/sonar/debts/model.py:135-153), replace the sum of every matching debit after `balance_as_of` (:141-147) with a small private pure helper. The helper takes the schedule `payments` already built at :137, the matching debits, and `today`, and applies D1 with D3. Update the why-comment to match.
  Add the D5 bullet at the end of SPEC.md §13. Apply D4 to tests/web/test_api_debts.py:230-246.
Context: D1 rule: for each scheduled payment with `due_date <= today`, take at most one matching debit with |booking_date - due_date| <= `schedule.TOLERANCE` (src/sonar/recurring/schedule.py:15, already imported at model.py:16) and abs amount >= the payment's `amount_cents`, the closest to the due date. A debit is used at most once, and it counts at the scheduled `amount_cents`. D2: below-amount, off-window and not-yet-due debits do not count, and that is intended. D3: due dates ascending, ties go to the earlier booking date. D4: in that test only, post the loan with `rate_cents: 10_000` and insert an M-2 debit on 2026-07-30 via `_insert_tx` (:77), keeping `paid_cents == 10_000`. D5: one new §13 bullet that says extra repayments do not count. `LoanPayment` fields: amortization.py:25-28. Installments, projection, payoff and `debt_schedule` stay unchanged. Integer cents only.
Read: `src/sonar/debts/model.py`, `src/sonar/debts/amortization.py`, `tests/debts/test_model_status.py`, `tests/web/test_api_debts.py`, `SPEC.md`
Write: `src/sonar/debts/model.py`, `tests/debts/test_model_paid_since.py`, `tests/web/test_api_debts.py`, `SPEC.md`
Test first: in a new file `tests/debts/test_model_paid_since.py`, with fake mandates such as "M-SHARED" and the `_tx` shape of tests/debts/test_model_status.py:16-32, these tests all call `loan_status` and fail before the change:
  (a) Shared debit: three linear loans, each with balance 100_000, as_of 2026-06-30 and rates 3_214, 4_311 and 2_558, on one mandate. A combined -10_083 debit falls on each of 2026-07-30 and 2026-08-30, and today is 2026-09-23. The loans' paid since are 6_428, 8_622 and 5_116.
  (b) Unrelated debits: smaller same-mandate debits inside the window, and larger ones 8 or more days from a due date, add nothing.
  (c) One per due date: two qualifying debits within the window of one due date count that payment once.
  (d) Final payment: a linear loan with balance 25_000, as_of 2026-06-30 and rate 10_000 is scheduled to pay 10_000, 10_000 and 5_000. With -10_000 debits on 2026-07-30, 08-30 and 09-30 and today 2026-10-01, paid since is 25_000.
  (e) Ordinary loan: the existing scenario at test_model_status.py:38-65 still gives 200_000. That test stays unchanged.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts/test_model_paid_since.py tests/debts/test_model_status.py tests/web/test_api_debts.py tests/web/test_debts_page.py`
- C2 [review] The tests (a)-(e) exist with these numbers. The helper is pure, takes `today` as a parameter, uses integer cents, matches D1 and D3, and counts each debit at most once. `installment_status`, `debt_schedule`, projection and payoff are unchanged. The only edit to an existing test is the D4 one, at test_api_debts.py:230-246. SPEC.md gains exactly one §13 bullet that states D1 and that extra repayments do not count.
- C3 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-11-02
exec: DONE · 2076 passed; ruff check and format check clean
- Count matching loan debits once per due payment at the scheduled amount; add regressions and the SPEC §13 amendment.
- Choose closest qualifying debit with earlier booking date for ties; adjust only the specified existing API test.
check: PASS 2/2
verify: PASS
