# Expected income uses the lowest salary
status: DONE
created: 2026-10-07 · updated: 2026-10-08
goal: The dashboard's expected monthly income counts the lowest salary of the last 3 complete pay cycles, not the highest.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: Expected monthly income (the runway's right end and the `expected_income` of `/api/dashboard`) becomes a conservative estimate: the salary part is the lowest per-cycle salary sum of the last 3 complete pay cycles, the way banks assess income, instead of the highest.

In scope: the salary selection in `src/sonar/cashflow/income.py`, its module docstring, the income tests written test-first, the test expectations elsewhere that pin the old highest-salary value, and the SPEC §13 sentence that defines expected salary.

Out of scope: templates, CSS, the runway chart geometry, the fixed-cost pay cycles, recurring income (still added unchanged), and the known 375px legend overflow.

Constraints: AGENTS.md rules: strict TDD (failing test first), pure functions with `estimate_date` passed in, integer cents, ruff check and format clean. No template change, so no visual gate. Decisions D1-D3 below.

Definition of done: a test with three different salaries in the 3 complete cycles expects the lowest; the existing income tests follow the new rule; `uv run pytest`, `ruff check .` and `ruff format --check .` pass.

## Decisions

- D1 A complete cycle with no salary credit (history shorter than 3 cycles, or a gap) is skipped: expected salary is the lowest of the cycles that have one, and 0 (no expected income) only when none has | confirmed
- D2 SPEC wording: SPEC.md:256 ("Expected salary is the highest, over the 3 complete pay cycles ...") is edited in place to "lowest" with "of the cycles that have such credits" per D1, rather than a new §13 amendment | confirmed
- D3 Tests outside `tests/cashflow/test_income.py` that assert the old highest-salary value are updated to the lowest (tests/cashflow/test_service.py:807, tests/web/test_api_dashboard.py:136, tests/web/test_dashboard_page.py:698,700,722); no other behavior changes | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | lowest salary of the last 3 complete cycles | exec | - | sonnet/sonnet | 1 | 0 | DONE | |

## N01 lowest salary of the last 3 complete cycles
Do: Change the expected salary in `src/sonar/cashflow/income.py` from the highest to the lowest per-cycle salary
  sum of the 3 complete pay cycles; cycles without any salary credit are skipped, and with none at all the
  result stays None. Rename `_best_salary` to a name that says what it picks, update the module docstring
  (line 3 says "best salary"), and change the SPEC §13 sentence that defines expected salary. Recurring income
  is untouched.
Context: D1 cycles with no salary credit are skipped; lowest of the rest; none gives 0 and so None.
  D2 edit SPEC.md:256 in place: "Expected salary is the highest, over the 3 complete pay cycles ..." becomes
  the lowest, over those of the 3 cycles that have such credits, keeping the rest of the sentence.
  D3 update the old highest-salary expectations in tests/cashflow/test_service.py:807,
  tests/web/test_api_dashboard.py:136 and tests/web/test_dashboard_page.py:698,700,722 to the lowest value.
  Selection: src/sonar/cashflow/income.py:46-67 (`max(...)` at :57). Worked example test:
  tests/cashflow/test_income.py:36-50 (cycles 300000, 330000, 310000; expects 330000 today).
Read: `src/sonar/cashflow/income.py`, `tests/cashflow/test_income.py`, `SPEC.md`
Write: `src/sonar/cashflow/income.py`, `tests/cashflow/test_income.py`, `tests/cashflow/test_service.py`, `tests/web/test_api_dashboard.py`, `tests/web/test_dashboard_page.py`, `SPEC.md`
Test first: in tests/cashflow/test_income.py, three different salaries in the 3 complete cycles give the lowest
  as `salary_cents`, and one salary cycle plus two empty ones gives that salary; both fail on the current code.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_income.py -k "lowest"` passes a test where three different
  salaries in the 3 complete cycles yield the minimum as salary_cents
- C2 [review] tests/cashflow/test_income.py: the worked example (renamed, no "best") expects salary 300000 and
  total 325500; a test with salary in only 1 of the 3 cycles expects that salary (D1); no-salary tests still expect None
- C3 [review] src/sonar/cashflow/income.py picks the minimum over cycles with a nonzero salary sum, has no
  `max(` in the salary selection and no "best" in names or docstring; `_recurring_monthly` is unchanged
- C4 [review] SPEC.md:256 says lowest over the 3 complete cycles that have salary credits; no other SPEC line changed
- C5 [review] the only changes in tests/cashflow/test_service.py, tests/web/test_api_dashboard.py and
  tests/web/test_dashboard_page.py are expected salary/income values; git diff shows no template or CSS file
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-08
exec: DONE · 1311 passed
- expected salary is now the lowest nonzero per-cycle salary sum (_lowest_salary); SPEC §13 line 256 updated
- old highest-salary expectations changed to the lowest value in 4 tests; 2 new lowest tests
check: PASS 2/2
verify: PASS
